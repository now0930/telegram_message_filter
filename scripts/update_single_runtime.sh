#!/usr/bin/env bash
set -Eeuo pipefail

# Update one flat runtime directory from a temporary clone. The temporary
# checkout is removed automatically; persistent credentials and databases stay
# in the runtime directory.

die() {
  printf '오류: %s\n' "$*" >&2
  exit 1
}

script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${RUNTIME_DIR:-$HOME/telegram_message_filter}"
repo_url="${REPO_URL:-$(git -C "$script_root" config --get remote.origin.url 2>/dev/null || true)}"

[[ -d "$runtime_dir" ]] || die "실행 디렉터리가 없습니다: $runtime_dir"
[[ -f "$runtime_dir/.env" ]] || die "기존 .env가 없습니다: $runtime_dir/.env"
[[ -n "$repo_url" ]] || die "원격 저장소 주소가 없습니다. REPO_URL을 지정하세요."
command -v git >/dev/null 2>&1 || die "git이 필요합니다."
command -v docker >/dev/null 2>&1 || die "docker가 필요합니다."

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/telegram-filter-update.XXXXXX")"
backup_dir="$(mktemp -d "${TMPDIR:-/tmp}/telegram-filter-backup.XXXXXX")"
restore_needed=0

cleanup() {
  rm -rf -- "$tmp_dir" "$backup_dir"
}

restore_on_error() {
  status=$?
  if (( status != 0 )) && (( restore_needed )); then
    printf '업데이트 실패: 이전 코드 복원을 시도합니다.\n' >&2
    for file in "${tracked_files[@]}"; do
      if [[ -e "$backup_dir/$file" ]]; then
        cp -a "$backup_dir/$file" "$runtime_dir/$file"
      fi
    done
    docker compose \
      -f "$runtime_dir/docker-compose.yml" \
      -f "$runtime_dir/docker-compose.deals.yml" \
      up -d --force-recreate telegram-filter >/dev/null 2>&1 || true
  fi
  cleanup
  exit "$status"
}

trap restore_on_error EXIT

tracked_files=(
  .env.example .gitignore README.md deal_bridge.py deal_filter.py
  docker-compose.deals.yml docker-compose.yml main.py news_filter.py
  portal_verifier.py telegram_delivery.py requirements.txt bond_monitor.py bond_watchlist.example.json
)

printf '임시 clone: %s\n' "$repo_url"
git clone --depth=1 "$repo_url" "$tmp_dir/repository"
staged_dir="$tmp_dir/repository/telegram_message_filter"
[[ -f "$staged_dir/docker-compose.yml" ]] || die "새 저장소의 실행 파일을 찾지 못했습니다."
[[ -f "$staged_dir/docker-compose.deals.yml" ]] || die "당근 Compose 설정을 찾지 못했습니다."

printf '새 커밋: '
git -C "$tmp_dir/repository" log -1 --oneline

# Validate the staged compose files with the current runtime secrets/settings.
staged_runtime="$tmp_dir/runtime"
mkdir -p "$staged_runtime"
for file in "${tracked_files[@]}"; do
  [[ -f "$staged_dir/$file" ]] && cp -a "$staged_dir/$file" "$staged_runtime/$file"
done
for file in .env telegram_session.session news_history.sqlite3 deal_notifications.sqlite3 deal_watchlist.json; do
  [[ -e "$runtime_dir/$file" ]] && cp -a "$runtime_dir/$file" "$staged_runtime/$file"
done
if [[ ! -e "$staged_runtime/deal_watchlist.json" ]]; then
  cp -a "$staged_dir/deal_watchlist.json" "$staged_runtime/deal_watchlist.json"
fi
if [[ ! -e "$staged_runtime/bond_watchlist.json" ]]; then
  cp -a "$staged_dir/bond_watchlist.example.json" "$staged_runtime/bond_watchlist.json"
fi
docker compose \
  -f "$staged_runtime/docker-compose.yml" \
  -f "$staged_runtime/docker-compose.deals.yml" \
  config >/dev/null

if [[ "${SINGLE_RUNTIME_CONFIRM:-}" != "YES" ]]; then
  [[ -t 0 ]] || die "비대화형 실행은 SINGLE_RUNTIME_CONFIRM=YES를 지정하세요."
  read -r -p "기존 서비스 코드를 최신 커밋으로 교체할까요? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || die "사용자가 취소했습니다. 기존 서비스는 변경하지 않았습니다."
fi

# Keep a temporary rollback copy of tracked runtime files only.
for file in "${tracked_files[@]}"; do
  [[ -e "$runtime_dir/$file" ]] && cp -a "$runtime_dir/$file" "$backup_dir/$file"
done

docker compose \
  -f "$runtime_dir/docker-compose.yml" \
  -f "$runtime_dir/docker-compose.deals.yml" \
  down
restore_needed=1

for file in "${tracked_files[@]}"; do
  [[ -f "$staged_dir/$file" ]] && cp -a "$staged_dir/$file" "$runtime_dir/$file"
done

docker compose \
  -f "$runtime_dir/docker-compose.yml" \
  -f "$runtime_dir/docker-compose.deals.yml" \
  up -d --force-recreate telegram-filter
restore_needed=0

docker compose \
  -f "$runtime_dir/docker-compose.yml" \
  -f "$runtime_dir/docker-compose.deals.yml" \
  ps
docker compose \
  -f "$runtime_dir/docker-compose.yml" \
  -f "$runtime_dir/docker-compose.deals.yml" \
  logs --tail=100 telegram-filter

printf '\n완료: 운영 디렉터리는 하나만 사용합니다: %s\n' "$runtime_dir"
printf '임시 clone은 삭제되었습니다. 다른 next/backup 디렉터리는 자동으로 삭제하지 않았습니다.\n'
