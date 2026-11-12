#!/usr/bin/env bash
# Shared by deploy/selfhost/update.sh and tools/work.sh: free-space check before a backup and
# safe pruning of finished backup files. Source it; it runs nothing and sets no shell options.
# Portable bash (3.2 on macOS and Ubuntu); no associative arrays, no mapfile, no GNU-only flags.
#
# Free space (backup_check_space): a new backup is written only when the directory has at least
#   max(size of the newest finished backup * SIDEKICK_BACKUP_SPACE_MARGIN_PCT / 100, SIDEKICK_BACKUP_SPACE_FLOOR_MB)
# free. Defaults: 150 (percent, at least 100) and 64 (MiB). The first backup has no earlier size to compare with,
# so only the floor applies. A free size that cannot be read counts as a refusal, never as "enough".
#
# Pruning (backup_prune_finished): touches only regular files (no symlinks) whose whole name matches the given
# extended regular expression, which the caller builds from the exact finished-backup name form (time stamp
# included). A temporary, hidden or half-written file never matches. It keeps the newest KEEP matching files
# (KEEP is at least 1, so the newest finished backup is never removed), never removes the protected file, and does
# nothing unless the protected file (the backup just written and read back) is there and not empty.

BACKUP_SPACE_MARGIN_PCT_DEFAULT=150
BACKUP_SPACE_FLOOR_MB_DEFAULT=64

backup_is_uint() {
  case "$1" in '' | *[!0-9]*) return 1 ;; esac
  return 0
}

# backup_valid_keep VALUE: a whole number of at least 1.
backup_valid_keep() {
  backup_is_uint "$1" || return 1
  [ "$((10#$1))" -ge 1 ]
}

# backup_free_bytes DIR: bytes available to this user on the file system of DIR; fails when it cannot be read.
backup_free_bytes() {
  local kib
  kib="$(df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}')" || return 1
  backup_is_uint "$kib" || return 1
  printf '%s\n' "$((10#$kib * 1024))"
}

# backup_list_finished DIR ERE: the names in DIR that match ^(ERE)$ and are regular files, oldest first.
backup_list_finished() {
  local name
  [ -d "$1" ] || return 0
  { ls -1 "$1" 2>/dev/null | grep -E "^($2)\$" | LC_ALL=C sort; } | while IFS= read -r name; do
    if [ -f "$1/$name" ] && [ ! -L "$1/$name" ]; then printf '%s\n' "$name"; fi
  done || true
}

# backup_newest_size DIR ERE: size in bytes of the newest finished file (by name, which holds the time), 0 if none.
backup_newest_size() {
  local name bytes
  name="$(backup_list_finished "$1" "$2" | tail -n 1)"
  if [ -z "$name" ]; then
    printf '0\n'
    return 0
  fi
  bytes="$(wc -c <"$1/$name" | tr -d ' ')"
  printf '%s\n' "${bytes:-0}"
}

# backup_check_space DIR BASELINE_BYTES. Sets BACKUP_SPACE_NEEDED and BACKUP_SPACE_FREE (bytes) when it can.
# Returns 0 enough room, 1 too little, 2 the free size could not be read, 3 a setting is not a valid number.
BACKUP_SPACE_NEEDED=0
BACKUP_SPACE_FREE=0
backup_check_space() {
  local margin floor_mb needed floor_bytes free
  margin="${SIDEKICK_BACKUP_SPACE_MARGIN_PCT:-$BACKUP_SPACE_MARGIN_PCT_DEFAULT}"
  floor_mb="${SIDEKICK_BACKUP_SPACE_FLOOR_MB:-$BACKUP_SPACE_FLOOR_MB_DEFAULT}"
  backup_is_uint "$margin" || return 3
  backup_is_uint "$floor_mb" || return 3
  backup_is_uint "$2" || return 3
  [ "$((10#$margin))" -ge 100 ] || return 3
  needed="$((10#$2 * 10#$margin / 100))"
  floor_bytes="$((10#$floor_mb * 1048576))"
  if [ "$needed" -lt "$floor_bytes" ]; then needed="$floor_bytes"; fi
  BACKUP_SPACE_NEEDED="$needed"
  free="$(backup_free_bytes "$1")" || return 2
  BACKUP_SPACE_FREE="$free"
  [ "$free" -ge "$needed" ]
}

# backup_prune_finished DIR ERE KEEP PROTECTED_NAME. Prints the number of files removed. Returns 1 for a bad KEEP.
backup_prune_finished() {
  local dir="$1" ere="$2" keep="$3" protected="$4" name removed=0
  backup_valid_keep "$keep" || return 1
  if [ -z "$protected" ] || [ ! -f "$dir/$protected" ] || [ ! -s "$dir/$protected" ] || [ -L "$dir/$protected" ]; then
    printf '0\n'
    return 0
  fi
  while IFS= read -r name; do
    [ "$name" = "$protected" ] && continue
    if rm -f -- "$dir/$name"; then removed=$((removed + 1)); fi
  done < <(backup_list_finished "$dir" "$ere" | LC_ALL=C sort -r | tail -n "+$((10#$keep + 1))")
  printf '%s\n' "$removed"
}
