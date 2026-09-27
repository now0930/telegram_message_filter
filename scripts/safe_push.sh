#!/usr/bin/env bash
set -Eeuo pipefail

# Push only a clean, fast-forwardable branch. No force push or automatic merge.

die() {
  printf '오류: %s\n' "$*" >&2
  exit 1
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Git 저장소 안에서 실행하세요."
cd "$repo_root"

remote="${PUSH_REMOTE:-origin}"
branch="$(git symbolic-ref --quiet --short HEAD)" || die "detached HEAD에서는 푸시하지 않습니다."

git remote get-url "$remote" >/dev/null 2>&1 || die "원격 저장소를 찾을 수 없습니다: $remote"

if ! git diff --quiet || ! git diff --cached --quiet; then
  die "커밋되지 않은 변경사항이 있습니다. 먼저 검토하고 커밋하세요."
fi
if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  die "추적되지 않은 파일이 있습니다. 비밀 파일인지 확인한 뒤 정리하세요."
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [[ -z "$upstream" ]]; then
  upstream="$remote/$branch"
fi

printf '원격 정보 갱신: %s\n' "$remote"
git fetch --prune "$remote"
git rev-parse --verify "$upstream" >/dev/null 2>&1 || die "추적 원격 브랜치가 없습니다: $upstream"

read -r behind ahead < <(git rev-list --left-right --count "$upstream...HEAD")
(( behind == 0 )) || die "원격이 $behind개 커밋 앞섭니다. 먼저 pull/rebase를 검토하세요."
(( ahead > 0 )) || {
  printf '이미 최신 상태입니다: %s\n' "$upstream"
  exit 0
}

git diff --check "$upstream..HEAD" || die "커밋에 공백 오류가 있습니다."

changed_files="$(git diff --name-only "$upstream..HEAD")"
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  case "$path" in
    *.env|*.env.*|*.session|*.session-*|*.sqlite3|*.sqlite3-*|*.pem|*.key|*credentials*|*secret*)
      die "비밀 또는 런타임 파일이 커밋 범위에 있습니다: $path"
      ;;
  esac
done <<< "$changed_files"

printf '\n푸시할 커밋 (%s개):\n' "$ahead"
git log --oneline --decorate "$upstream..HEAD"
printf '\n변경 파일:\n%s\n' "$changed_files"

if [[ "${PUSH_CONFIRM:-}" != "YES" ]]; then
  [[ -t 0 ]] || die "비대화형 실행은 PUSH_CONFIRM=YES를 지정하세요."
  read -r -p "위 내용을 확인했고 $remote/$branch 로 푸시할까요? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || die "사용자가 취소했습니다."
fi

# Plain push is fast-forward only; this script never force-pushes.
git push "$remote" "$branch"
printf '푸시 완료: %s/%s\n' "$remote" "$branch"
