"""A small simulated network so ping/tracert/nslookup/netstat/arp behave like a
real segmented enterprise LAN. Entirely deterministic — no external calls, ever.

The topology tells a story: the compromised DC sits on the server VLAN, can see
a few internal hosts, and cannot egress to the internet directly (typical of a
locked-down segment) except to one suspicious IP the attacker used for exfil.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Host:
    ip: str
    names: tuple[str, ...]
    up: bool
    ttl: int
    os: str = ""
    ports: tuple[int, ...] = ()
    note: str = ""


# The DC's own identity.
SELF_IP = "10.20.5.10"
GATEWAY = "10.20.5.1"

HOSTS: tuple[Host, ...] = (
    Host("10.20.5.1", ("gw-core", "meridian-core"), True, 255, os="Cisco IOS",
         ports=(22, 443), note="Default gateway / core switch."),
    Host("10.20.5.10", ("meridian-dc01", "dc01"), True, 128, os="Windows Server 2019",
         ports=(53, 88, 135, 389, 445, 3389), note="This host — the domain controller."),
    Host("10.20.5.11", ("meridian-dc02", "dc02"), True, 128, os="Windows Server 2019",
         ports=(53, 88, 389, 445), note="Secondary domain controller."),
    Host("10.20.5.20", ("meridian-fs01", "fs01", "fileserver"), True, 128,
         os="Windows Server 2016", ports=(139, 445), note="File server."),
    Host("10.20.5.30", ("meridian-sql01", "sql01"), True, 128, os="Windows Server 2019",
         ports=(445, 1433), note="Accounting SQL database."),
    Host("10.20.5.40", ("meridian-web01", "web01", "intranet"), True, 128,
         os="Windows Server 2019", ports=(80, 443, 445),
         note="IIS intranet — hosts the uploaded webshell."),
    Host("10.20.9.7", ("wks-osei", "karen-pc"), True, 128, os="Windows 10",
         ports=(445, 3389), note="Karen Osei's workstation (accounting VLAN)."),
    Host("185.220.101.44", ("cdn-sync.blob-delivery.net",), True, 54,
         os="Linux", ports=(443,), note="Attacker exfil endpoint — do not trust."),
)

# Hosts on the same VLAN respond to ARP.
LOCAL_SUBNET = "10.20.5."


def find_host(target: str) -> Host | None:
    t = target.strip().lower()
    for h in HOSTS:
        if t == h.ip or t in h.names:
            return h
    return None


def resolve_name(target: str) -> tuple[str, str] | None:
    """Return (fqdn-ish name, ip) for nslookup, or None if it doesn't resolve."""
    h = find_host(target)
    if h is None:
        return None
    # Prefer a dotted name if one exists, else <name>.meridian.local
    name = next((n for n in h.names if "." in n), h.names[0] + ".meridian.local")
    return name, h.ip


def ping(target: str, count: int = 4) -> str:
    h = find_host(target)
    if h is None:
        return (
            f"Ping request could not find host {target}. Please check the name "
            "and try again."
        )
    header = f"\nPinging {h.names[0]} [{h.ip}] with 32 bytes of data:"
    lines = [header]
    if not h.up:
        lines += ["Request timed out."] * count
        lines.append(f"\nPing statistics for {h.ip}:")
        lines.append(
            f"    Packets: Sent = {count}, Received = 0, Lost = {count} (100% loss),"
        )
        return "\n".join(lines)
    times = [31, 29, 30, 28][:count]
    for t in times:
        lines.append(f"Reply from {h.ip}: bytes=32 time={t}ms TTL={h.ttl}")
    avg = sum(times) // len(times)
    lines.append(f"\nPing statistics for {h.ip}:")
    lines.append(
        f"    Packets: Sent = {count}, Received = {count}, Lost = 0 (0% loss),"
    )
    lines.append("Approximate round trip times in milli-seconds:")
    lines.append(
        f"    Minimum = {min(times)}ms, Maximum = {max(times)}ms, Average = {avg}ms"
    )
    return "\n".join(lines)


def tracert(target: str) -> str:
    h = find_host(target)
    if h is None:
        return (
            f"Unable to resolve target system name {target}."
        )
    lines = [f"\nTracing route to {h.names[0]} [{h.ip}]", "over a maximum of 30 hops:\n"]
    if h.ip.startswith(LOCAL_SUBNET):
        lines.append(f"  1     1 ms     1 ms     1 ms  {h.ip}")
    elif h.ip.startswith("10.20."):
        lines.append(f"  1     1 ms    <1 ms    <1 ms  {GATEWAY}")
        lines.append(f"  2     2 ms     2 ms     1 ms  {h.ip}")
    else:
        # External: egress is filtered, so it dies at the perimeter firewall.
        lines.append(f"  1    <1 ms    <1 ms    <1 ms  {GATEWAY}")
        lines.append("  2     *        *        *     Request timed out.")
        lines.append("  3     *        *        *     Request timed out.")
        lines.append("  4  fw-edge01 [10.20.0.1]  reports: Destination net unreachable.")
        lines.append("\nTrace complete.")
        return "\n".join(lines)
    lines.append("\nTrace complete.")
    return "\n".join(lines)


def nslookup(target: str) -> str:
    resolved = resolve_name(target)
    server = "Server:  dc01.meridian.local\nAddress:  10.20.5.10\n"
    if resolved is None:
        return server + f"\n*** dc01.meridian.local can't find {target}: Non-existent domain"
    name, ip = resolved
    return server + f"\nName:    {name}\nAddress:  {ip}"


def arp() -> str:
    lines = ["", f"Interface: {SELF_IP} --- 0x5", "  Internet Address      Physical Address      Type"]
    mac = 0x1A
    for h in HOSTS:
        if h.ip.startswith(LOCAL_SUBNET) and h.ip != SELF_IP:
            phys = f"00-50-56-{mac:02x}-3f-{mac + 5:02x}"
            lines.append(f"  {h.ip:<21} {phys:<21} dynamic")
            mac += 1
    lines.append(f"  10.20.5.255           ff-ff-ff-ff-ff-ff     static")
    return "\n".join(lines)


def netstat() -> str:
    return (
        "\nActive Connections\n\n"
        "  Proto  Local Address          Foreign Address        State\n"
        "  TCP    10.20.5.10:445         10.20.5.20:52133       ESTABLISHED\n"
        "  TCP    10.20.5.10:3389        10.20.9.7:60112        ESTABLISHED\n"
        "  TCP    10.20.5.10:389         10.20.5.11:49201       ESTABLISHED\n"
        "  TCP    10.20.5.10:49761       185.220.101.44:443     ESTABLISHED\n"
        "  TCP    10.20.5.10:135         0.0.0.0:0              LISTENING\n"
        "  TCP    10.20.5.10:445         0.0.0.0:0              LISTENING\n"
        "  TCP    10.20.5.10:3389        0.0.0.0:0              LISTENING\n"
    )


def ipconfig() -> str:
    return (
        "\nWindows IP Configuration\n\n\n"
        "Ethernet adapter Ethernet0:\n\n"
        "   Connection-specific DNS Suffix  . : meridian.local\n"
        f"   IPv4 Address. . . . . . . . . . . : {SELF_IP}\n"
        "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\n"
        f"   Default Gateway . . . . . . . . . : {GATEWAY}\n"
    )


def http_fetch(url: str) -> str:
    """Simulate curl / Invoke-WebRequest. Internal intranet answers; the exfil
    host answers with an attacker beacon; everything else is blocked at egress."""
    u = url.strip().lower()
    if "185.220.101.44" in u or "blob-delivery" in u:
        return "HTTP/1.1 200 OK\nServer: nginx\nContent-Length: 2\n\nok"
    if "web01" in u or "intranet" in u or "10.20.5.40" in u:
        return (
            "HTTP/1.1 200 OK\nServer: Microsoft-IIS/10.0\n\n"
            "<html><title>Meridian Intranet</title>...</html>"
        )
    return (
        "curl: (7) Failed to connect: outbound HTTP is blocked by perimeter "
        "firewall fw-edge01."
    )
