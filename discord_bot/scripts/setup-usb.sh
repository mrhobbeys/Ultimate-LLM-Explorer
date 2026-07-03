#!/usr/bin/env bash
#
# Smart USB/SSD setup for I/O offloading — spares the SD card's write lifespan.
# Detects a USB drive; if none is present it asks you to plug one in and waits;
# then it mounts it, makes the mount persistent (fstab, by UUID, with `nofail`
# and `noatime`), and prints the chosen data directory.
#
# Called by the onboarding wizard, but also runnable standalone:
#     sudo bash scripts/setup-usb.sh [OUTPUT_FILE]
# If OUTPUT_FILE is given, the resulting data dir is written there as
#     PIBOT_DATA_DIR=/mnt/pibot/pibot-data
#
set -euo pipefail
OUT="${1:-}"
MOUNTPOINT="/mnt/pibot"
c_g='\033[0;32m'; c_y='\033[1;33m'; c_r='\033[0;31m'; c_0='\033[0m'
ok(){ echo -e "${c_g}  ✓${c_0} $*"; }; warn(){ echo -e "${c_y}  !${c_0} $*"; }
err(){ echo -e "${c_r}  ✗ $*${c_0}" >&2; }

[ "$(id -u)" -eq 0 ] || { err "USB auto-setup needs root. Re-run with sudo, or set a data path by hand."; exit 2; }

usb_disks() { lsblk -rpno NAME,TYPE,TRAN | awk '$2=="disk" && $3=="usb"{print $1}'; }

# ---- 1. find a USB disk, prompting for insertion if needed ---------------- #
tries=0
while [ -z "$(usb_disks)" ]; do
  tries=$((tries+1))
  if [ "$tries" -gt 6 ]; then
    warn "No USB drive detected after several tries — skipping USB offload."
    exit 3
  fi
  echo -e "${c_y}No USB drive detected.${c_0} Plug one in now."
  read -r -p "  Press Enter to re-scan (or type 'skip' to cancel): " ans || ans="skip"
  [ "$ans" = "skip" ] && exit 3
  sleep 2
done

echo "Detected USB disk(s):"
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT $(usb_disks) 2>/dev/null || true
echo

# ---- 2. already mounted? offer to reuse ----------------------------------- #
for disk in $(usb_disks); do
  mp="$(lsblk -rpno NAME,MOUNTPOINT "$disk" | awk 'NF==2 && $2!="" && $2!="/"{print $2; exit}')"
  if [ -n "${mp:-}" ]; then
    read -r -p "  A USB partition is already mounted at $mp. Use it? (Y/n) " a || a=y
    if [[ ! "$a" =~ ^[Nn] ]]; then
      DATA="$mp/pibot-data"; mkdir -p "$DATA"
      ok "Using existing mount: $DATA"
      [ -n "$OUT" ] && echo "PIBOT_DATA_DIR=$DATA" > "$OUT"
      echo "PIBOT_DATA_DIR=$DATA"; exit 0
    fi
  fi
done

# ---- 3. pick a partition (or whole disk) ---------------------------------- #
mapfile -t PARTS < <(lsblk -rpno NAME,TYPE,SIZE $(usb_disks) | awk '$2=="part"{print $1" ("$3")"}')
if [ "${#PARTS[@]}" -eq 0 ]; then
  # no partitions — offer the whole first disk (will need formatting)
  DISK="$(usb_disks | head -1)"
  PARTS=("$DISK (whole disk, unpartitioned)")
fi
echo "Choose the target:"
i=1; for p in "${PARTS[@]}"; do echo "  [$i] $p"; i=$((i+1)); done
read -r -p "  Number: " sel || sel=1
TARGET="$(echo "${PARTS[$((sel-1))]}" | awk '{print $1}')"
[ -b "$TARGET" ] || { err "Not a block device: $TARGET"; exit 1; }

# ---- 4. format or use as-is ----------------------------------------------- #
FSTYPE="$(lsblk -rpno FSTYPE "$TARGET" | head -1)"
DO_FORMAT=0
if [ -z "$FSTYPE" ]; then
  warn "No filesystem on $TARGET — it must be formatted."
  DO_FORMAT=1
else
  echo "  $TARGET has an existing $FSTYPE filesystem."
  read -r -p "  [1] Use it as-is   [2] FORMAT as ext4 (ERASES ALL DATA)  → " c || c=1
  [ "$c" = "2" ] && DO_FORMAT=1
fi
if [ "$DO_FORMAT" -eq 1 ]; then
  echo -e "${c_r}  This will PERMANENTLY ERASE $TARGET.${c_0}"
  read -r -p "  Type FORMAT to confirm: " conf || conf=""
  [ "$conf" = "FORMAT" ] || { err "Not confirmed — aborting."; exit 1; }
  umount "$TARGET" 2>/dev/null || true
  mkfs.ext4 -F -L pibot "$TARGET" >/dev/null
  ok "formatted $TARGET as ext4"
fi

# ---- 5. mount + persist in fstab (by UUID) -------------------------------- #
mkdir -p "$MOUNTPOINT"
UUID="$(blkid -s UUID -o value "$TARGET")"
[ -n "$UUID" ] || { err "Could not read UUID of $TARGET"; exit 1; }
FSTYPE="$(lsblk -rpno FSTYPE "$TARGET" | head -1)"; FSTYPE="${FSTYPE:-ext4}"
# noatime = fewer writes (SD/USB longevity); nofail = boot won't hang if removed
FSTAB_LINE="UUID=$UUID $MOUNTPOINT $FSTYPE defaults,noatime,nofail 0 2"
if ! grep -q "$UUID" /etc/fstab; then
  echo "$FSTAB_LINE" >> /etc/fstab
  ok "added persistent mount to /etc/fstab"
fi
mount "$MOUNTPOINT" 2>/dev/null || mount -a
mountpoint -q "$MOUNTPOINT" && ok "mounted at $MOUNTPOINT" || { err "mount failed"; exit 1; }

DATA="$MOUNTPOINT/pibot-data"
mkdir -p "$DATA/backups"
# service user may not exist yet at onboarding time; installer re-chowns later
id pibot >/dev/null 2>&1 && chown -R pibot:pibot "$DATA" || true
ok "data directory ready: $DATA"

[ -n "$OUT" ] && echo "PIBOT_DATA_DIR=$DATA" > "$OUT"
echo "PIBOT_DATA_DIR=$DATA"
