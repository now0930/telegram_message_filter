#!/usr/bin/env bash
set -Eeuo pipefail

# Clone a fresh checkout and replace the running compose service without
# deleting the previous directory or its persistent files.

die() {
  printf '오류: %s\n' "$*" >&2
  exit 1
}

old_dir="${OLD_DIR:-/home/now0930/telegram_message_filter}"
new_dir="${NEW_DIR:-/home/now0930/telegram_message_filter_next}"
repo_url="${REPO_URL:-https://github.com/now0930/telegram_message_filter.git}"

[[ -d "$old_dir" ]] || die "기존 실행 디렉터리가 없습니다: $old_dir"
[[ ! -e "$new_dir" ]] || die "새 디렉터리가 이미 존재합니다: $new_dir"
[[ -f "$old_dir/.env" ]] || die "기존 .env를 찾을 수 없습니다: $old_dir/.env"
command -v git >/dev/null 2>&1 || die "git이 필요합니다."
command -v docker >/dev/null 2>&1 || die "docker가 필요합니다."

printf '새 저장소 clone: %s\n' "$new_dir"
git clone "$repo_url" "$new_dir"

app_dir="$new_dir/telegram_message_filter"
compose_file="$app_dir/docker-compose.yml"
deals_compose_file="$app_dir/docker-compose.deals.yml"
[[ -f "$compose_file" ]] || die "새 저장소에 docker-compose.yml이 없습니다."
[[ -f "$deals_compose_file" ]] || die "새 저장소에 docker-compose.deals.yml이 없습니다."

printf '새 커밋: '
git -C "$new_dir" log -1 --oneline

# These files are deliberately outside Git and must be carried over manually.
for file in .env telegram_session.session news_history.sqlite3 deal_notifications.sqlite3 deal_watchlist.json; do
  if [[ -e "$old_dir/$file" ]]; then
    cp -a "$old_dir/$file" "$app_dir/$file"
    printf '보존 파일 복사: %s\n' "$file"
  fi
done

docker compose \
  -f "$compose_file" \
  -f "$deals_compose_file" \
  config >/dev/null

if [[ "${CLONE_RESTART_CONFIRM:-}" != "YES" ]]; then
  [[ -t 0 ]] || die "비대화형 실행은 CLONE_RESTART_CONFIRM=YES를 지정하세요."
  read -r -p "기존 컨테이너를 중지하고 새 clone을 시작할까요? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || die "사용자가 취소했습니다. 기존 서비스는 변경하지 않았습니다."
fi

printf '기존 서비스 중지\n'
docker compose \
  -f "$old_dir/docker-compose.yml" \
  -f "$old_dir/docker-compose.deals.yml" \
  down

printf '새 서비스 시작\n'
docker compose \
  -f "$compose_file" \
  -f "$deals_compose_file" \
  up -d --force-recreate telegram-filter

docker compose \
  -f "$compose_file" \
  -f "$deals_compose_file" \
  ps
docker compose \
  -f "$compose_file" \
  -f "$deals_compose_file" \
  logs --tail=100 telegram-filter

printf '\n재시작 완료. 실시간 로그: docker compose -f %q -f %q logs -f telegram-filter\n' \
  "$compose_file" "$deals_compose_file"
