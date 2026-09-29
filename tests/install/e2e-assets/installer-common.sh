#!/usr/bin/env bash
# Driver-only setup; these helpers never install into the caller's real HOME.
arm_source_redirect() {
  local repo="$1" work="$2" serve="$3"
  local https='https://github.com/NousResearch/hermes-agent.git'
  local ssh='git@github.com:NousResearch/hermes-agent.git'
  local actual real_git quoted_git cfg="$work/gitconfig" shim="$work/shim"
  actual="$(git -C "$repo" remote get-url origin)"
  real_git="$(command -v git)"
  quoted_git="$(printf '%q' "$real_git")"
  # Export the real git so later checks can observe the TRANSPORT url. After
  # this function the shim shadows `git` and reports the official origin for
  # `remote get-url origin` (so fork detection sees it); any check that must see
  # the file:// redirect instead has to bypass the shim via this path.
  export HERMES_E2E_REAL_GIT="$real_git"
  # A global file survives install.sh replacing GIT_CONFIG_COUNT/KEY_n/VALUE_n.
  printf '' > "$cfg"
  for url in "$actual" "$https" "$ssh"; do
    "$real_git" config --file "$cfg" --add "url.file://$serve.insteadOf" "$url"
  done
  export GIT_CONFIG_GLOBAL="$cfg"
  [ "$(git -C "$repo" remote get-url origin)" = "file://$serve" ] \
    || fail 'git URL redirect did not reach the staged repository'

  # Transport is local, but fork detection must still see the official origin.
  mkdir -p "$shim"
  cat > "$shim/git" <<EOF
#!/usr/bin/env bash
prev2=""
prev1=""
for arg in "\$@"; do
  if [ "\$prev2" = remote ] && [ "\$prev1" = get-url ] && [ "\$arg" = origin ]; then
    printf '%s\n' '$https'
    exit 0
  fi
  prev2="\$prev1"
  prev1="\$arg"
done
exec $quoted_git "\$@"
EOF
  chmod +x "$shim/git"
  export PATH="$shim:$PATH"
  [ "$(git -C "$repo" remote get-url origin)" = "$https" ] \
    || fail 'git origin shim did not report the official repository'
  ok "git transport redirected via $cfg; origin reported by $shim/git"
}

# Print the commit an update ref names. NEXT is not a git ref: it mints a
# synthetic child of the install commit, so a leg that starts AT HEAD still
# has an update to take -- the one HEAD's own updater must handle. The child
# adds one marker file (a real tree diff, not an empty fast-forward) and
# lives only in the object store: no ref, no worktree change. A local
# `git clone --bare` copies objects/ wholesale, which is how it reaches
# serve.git; the drivers assert it arrived.
resolve_update_ref() {
  local repo="$1" parent="$2" ref="$3" blob tree
  if [ "$ref" != NEXT ]; then
    git -C "$repo" rev-parse "${ref}^{commit}"
    return
  fi
  blob="$(printf 'synthetic next commit for the HEAD -> NEXT install E2E leg\n' \
    | git -C "$repo" hash-object -w --stdin)" || return
  tree="$( { git -C "$repo" ls-tree -z "$parent"; printf '100644 blob %s\t.hermes-e2e-next\0' "$blob"; } \
    | git -C "$repo" mktree -z)" || return
  GIT_AUTHOR_NAME='Hermes E2E' GIT_AUTHOR_EMAIL='e2e@hermes.invalid' \
    GIT_COMMITTER_NAME='Hermes E2E' GIT_COMMITTER_EMAIL='e2e@hermes.invalid' \
    git -C "$repo" commit-tree "$tree" -p "$parent" -m 'e2e: synthetic next commit'
}

run_source_installer() {
  local repo="$1" work="$2" logs="$3" ref="$4" label="$5" desktop="${6:-}"
  local script="$work/install-$label.sh" help_text bindable_help rc=0
  git -C "$repo" show "$ref:scripts/install.sh" > "$script" || return
  local flags=()
  # Only usage/option entries in executable help count. A flag mentioned in
  # a rejection message or description is not a bindable capability.
  help_text="$(bash "$script" --help < /dev/null)" \
    || { fail "ref $ref installer --help failed; cannot safely select flags"; return 1; }
  bindable_help="$(grep -E '(^Usage:|^[[:space:]]+\[--)' <<< "$help_text")" || bindable_help=''
  if grep -Eq -- '--non-interactive([[:space:]]|\]|$)' <<< "$bindable_help"; then
    flags+=(--non-interactive)
  elif grep -Eq -- '--skip-setup([[:space:]]|\]|$)' <<< "$bindable_help"; then
    flags+=(--skip-setup)
  else
    fail "ref $ref advertises no non-interactive flag; cannot safely run"
    return 1
  fi
  if [ "$desktop" = desktop ]; then
    if ! grep -Eq -- '--include-desktop([[:space:]]|\]|$)' <<< "$bindable_help"; then
      fail "ref $ref does not advertise --include-desktop; this leg cannot mean what it claims"
      return 1
    fi
    flags+=(--include-desktop)
  fi
  # Pre-PM installers ran their own interactive browser install. The PM
  # installer advertises --manifest and owns browser setup as part of its
  # normal install; let that path run rather than disabling it.
  if grep -Eq -- '--skip-browser([[:space:]]|\]|$)' <<< "$bindable_help" \
    && ! grep -Eq -- '--manifest([[:space:]]|\]|$)' <<< "$bindable_help"; then
    flags+=(--skip-browser)
  fi
  bash "$script" "${flags[@]}" < /dev/null 2>&1 | ts_prefix > "$logs/install-$label.log" || rc=$?
  log_group "install.sh ($label) transcript" "$logs/install-$label.log"
  [ "$rc" -eq 0 ] || { fail "install.sh ($label) exited $rc; log at $logs/install-$label.log"; return "$rc"; }
}
