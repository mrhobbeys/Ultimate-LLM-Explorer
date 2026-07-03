"""Windows-style virtual filesystem over the Store.

Paths are case-insensitive (like NTFS), accept both ``\\`` and ``/`` separators,
support ``.``/``..``, drive-absolute (``C:\\...``), root-relative (``\\...``), and
relative forms. Every node carries an owner and a ``protected`` flag; mutations
under a protected subtree require ``admin`` or ``system`` privilege, which is how
"Access is denied." happens for real on a locked-down box.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import Node, Store

DRIVE = "C:"


class FSError(Exception):
    """Raised with a message already formatted the way Windows would print it."""


@dataclass
class ResolvedPath:
    """The outcome of resolving a path string: the normalized absolute path, the
    node if it exists (else None), and its parent node if that exists."""

    abspath: str
    node: Node | None
    parent: Node | None
    leaf_name: str


def split_components(raw: str) -> list[str]:
    """Split a path body (no drive) into components, honoring both separators."""
    return [c for c in raw.replace("/", "\\").split("\\") if c]


def normalize(path: str, cwd: str) -> str:
    """Resolve ``path`` against ``cwd`` into a canonical ``C:\\a\\b`` string.

    ``C:\\`` is the root. ``.`` and ``..`` are collapsed; ``..`` at root stays at
    root (Windows behavior). Case is preserved for display but matching is done
    case-insensitively downstream.
    """
    path = path.strip().strip('"')
    if not path:
        return cwd

    lower = path.lower()
    if lower.startswith("c:"):
        body = path[2:]
        base: list[str] = []
    elif path.startswith("\\") or path.startswith("/"):
        body = path
        base = []
    else:
        body = path
        base = split_components(cwd[len(DRIVE):])

    parts = base + split_components(body)
    stack: list[str] = []
    for part in parts:
        if part == ".":
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)

    if not stack:
        return DRIVE + "\\"
    return DRIVE + "\\" + "\\".join(stack)


class VirtualFS:
    def __init__(self, store: Store, player_key: str) -> None:
        self.store = store
        self.player_key = player_key

    # ---- resolution ----------------------------------------------------
    def _root(self) -> Node:
        root = self.store.get_root(self.player_key)
        if root is None:
            raise FSError("The system cannot find the path specified.")
        return root

    def resolve(self, path: str, cwd: str) -> ResolvedPath:
        abspath = normalize(path, cwd)
        components = split_components(abspath[len(DRIVE):])
        root = self._root()

        if not components:
            return ResolvedPath(abspath="C:\\", node=root, parent=None, leaf_name="")

        parent = root
        node: Node | None = root
        for i, comp in enumerate(components):
            child = self.store.get_child(self.player_key, parent.id, comp)
            if child is None:
                # Nothing at this component. If it's the last one, we still
                # return the parent so callers can create here.
                if i == len(components) - 1:
                    return ResolvedPath(
                        abspath=abspath, node=None, parent=parent, leaf_name=comp
                    )
                return ResolvedPath(
                    abspath=abspath, node=None, parent=None, leaf_name=comp
                )
            if i < len(components) - 1 and child.kind != "dir":
                # A file used as a directory in the middle of a path.
                return ResolvedPath(
                    abspath=abspath, node=None, parent=None, leaf_name=comp
                )
            parent = child if child.kind == "dir" else parent
            node = child
        parent_node = self.store.get_node(node.parent_id) if node.parent_id else None
        return ResolvedPath(
            abspath=abspath, node=node, parent=parent_node, leaf_name=components[-1]
        )

    def path_of(self, node: Node) -> str:
        parts: list[str] = []
        cur: Node | None = node
        while cur is not None and cur.parent_id is not None:
            parts.append(cur.name)
            cur = self.store.get_node(cur.parent_id)
        if not parts:
            return "C:\\"
        return DRIVE + "\\" + "\\".join(reversed(parts))

    # ---- permission helper --------------------------------------------
    def _writable(self, node: Node, privilege: str) -> bool:
        """Whether a player at ``privilege`` may modify/create/delete at ``node``
        (or, for creation, inside ``node``)."""
        if privilege in ("admin", "system"):
            return True
        return not node.protected

    # ---- reads ---------------------------------------------------------
    def list_dir(self, path: str, cwd: str) -> tuple[str, list[Node]]:
        rp = self.resolve(path, cwd)
        if rp.node is None:
            raise FSError("File Not Found")
        if rp.node.kind != "dir":
            # dir on a file lists just that file
            return self.path_of(rp.node), [rp.node]
        children = self.store.list_children(self.player_key, rp.node.id)
        return rp.abspath, children

    def read_file(self, path: str, cwd: str) -> str:
        rp = self.resolve(path, cwd)
        if rp.node is None:
            raise FSError("The system cannot find the file specified.")
        if rp.node.kind == "dir":
            raise FSError("Access is denied.")
        return rp.node.content

    def is_dir(self, path: str, cwd: str) -> bool:
        rp = self.resolve(path, cwd)
        return rp.node is not None and rp.node.kind == "dir"

    def exists(self, path: str, cwd: str) -> bool:
        return self.resolve(path, cwd).node is not None

    # ---- mutations -----------------------------------------------------
    def make_dir(self, path: str, cwd: str, privilege: str, owner: str) -> None:
        rp = self.resolve(path, cwd)
        if rp.node is not None:
            raise FSError("A subdirectory or file already exists.")
        if rp.parent is None:
            raise FSError("The system cannot find the path specified.")
        if not self._writable(rp.parent, privilege):
            raise FSError("Access is denied.")
        self.store.add_node(
            self.player_key, rp.parent.id, rp.leaf_name, "dir", owner=owner,
            protected=rp.parent.protected,
        )

    def remove_dir(self, path: str, cwd: str, privilege: str) -> None:
        rp = self.resolve(path, cwd)
        if rp.node is None:
            raise FSError("The system cannot find the file specified.")
        if rp.node.kind != "dir":
            raise FSError("The directory name is invalid.")
        if self.store.list_children(self.player_key, rp.node.id):
            raise FSError("The directory is not empty.")
        if rp.parent and not self._writable(rp.parent, privilege):
            raise FSError("Access is denied.")
        self.store.delete_node(rp.node.id)

    def remove_file(self, path: str, cwd: str, privilege: str) -> None:
        rp = self.resolve(path, cwd)
        if rp.node is None:
            raise FSError("Could Not Find " + normalize(path, cwd))
        if rp.node.kind == "dir":
            raise FSError("Access is denied.")
        if rp.parent and not self._writable(rp.parent, privilege):
            raise FSError("Access is denied.")
        self.store.delete_node(rp.node.id)

    def write_file(
        self, path: str, cwd: str, content: str, privilege: str, owner: str,
        append: bool = False,
    ) -> None:
        rp = self.resolve(path, cwd)
        if rp.node is not None:
            if rp.node.kind == "dir":
                raise FSError("Access is denied.")
            if rp.parent and not self._writable(rp.parent, privilege):
                raise FSError("Access is denied.")
            new = (rp.node.content + content) if append else content
            self.store.set_content(rp.node.id, new)
            return
        if rp.parent is None:
            raise FSError("The system cannot find the path specified.")
        if not self._writable(rp.parent, privilege):
            raise FSError("Access is denied.")
        self.store.add_node(
            self.player_key, rp.parent.id, rp.leaf_name, "file", content=content,
            owner=owner, protected=rp.parent.protected,
        )

    def _copy_tree(self, src: Node, dest_parent: int, new_name: str, owner: str) -> None:
        new_id = self.store.add_node(
            self.player_key, dest_parent, new_name, src.kind, content=src.content,
            owner=owner, protected=src.protected, hidden=src.hidden,
        )
        if src.kind == "dir":
            for child in self.store.list_children(self.player_key, src.id):
                self._copy_tree(child, new_id, child.name, owner)

    def _dest_target(
        self, src: Node, dest: str, cwd: str
    ) -> tuple[int, str]:
        """Given a source node and a destination path, return (parent_id, name)
        for where the copy/move should land. A directory destination means
        'inside it, same name'; anything else means the leaf name literally."""
        drp = self.resolve(dest, cwd)
        if drp.node is not None and drp.node.kind == "dir":
            return drp.node.id, src.name
        if drp.parent is None:
            raise FSError("The system cannot find the path specified.")
        return drp.parent.id, drp.leaf_name

    def copy(self, src: str, dest: str, cwd: str, privilege: str, owner: str) -> str:
        srp = self.resolve(src, cwd)
        if srp.node is None:
            raise FSError("The system cannot find the file specified.")
        parent_id, name = self._dest_target(srp.node, dest, cwd)
        dest_parent = self.store.get_node(parent_id)
        if dest_parent and not self._writable(dest_parent, privilege):
            raise FSError("Access is denied.")
        existing = self.store.get_child(self.player_key, parent_id, name)
        if existing is not None:
            if existing.kind == "dir":
                raise FSError("Access is denied.")
            self.store.set_content(existing.id, srp.node.content)
            return "        1 file(s) copied."
        self._copy_tree(srp.node, parent_id, name, owner)
        return "        1 file(s) copied."

    def move(self, src: str, dest: str, cwd: str, privilege: str) -> None:
        srp = self.resolve(src, cwd)
        if srp.node is None:
            raise FSError("The system cannot find the file specified.")
        if srp.parent and not self._writable(srp.parent, privilege):
            raise FSError("Access is denied.")
        parent_id, name = self._dest_target(srp.node, dest, cwd)
        dest_parent = self.store.get_node(parent_id)
        if dest_parent and not self._writable(dest_parent, privilege):
            raise FSError("Access is denied.")
        existing = self.store.get_child(self.player_key, parent_id, name)
        if existing is not None and existing.id != srp.node.id:
            if existing.kind == "dir":
                raise FSError("Access is denied.")
            self.store.delete_node(existing.id)
        self.store.reparent_node(srp.node.id, parent_id)
        if name.lower() != srp.node.name.lower():
            self.store.rename_node(srp.node.id, name)
        elif name != srp.node.name:
            self.store.rename_node(srp.node.id, name)

    def rename(self, src: str, new_name: str, cwd: str, privilege: str) -> None:
        srp = self.resolve(src, cwd)
        if srp.node is None:
            raise FSError("The system cannot find the file specified.")
        if srp.parent and not self._writable(srp.parent, privilege):
            raise FSError("Access is denied.")
        if "\\" in new_name or "/" in new_name:
            raise FSError("The syntax of the command is incorrect.")
        if self.store.get_child(self.player_key, srp.parent.id, new_name) and \
                new_name.lower() != srp.node.name.lower():
            raise FSError("A duplicate file name exists, or the file cannot be found.")
        self.store.rename_node(srp.node.id, new_name)
