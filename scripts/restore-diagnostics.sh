#!/usr/bin/env bash

restore_repository_error_code() {
  local message="${1,,}"
  case "$message" in
    *"restic_repository is required"*|*"restic_password is required"*)
      printf 'repository_bootstrap_missing'
      ;;
    *"wrong password"*|*"no key found"*)
      printf 'repository_password_invalid'
      ;;
    *"accessdenied"*|*"access denied"*|*"invalidaccesskeyid"*|*"nocredentialproviders"*|*"no valid credential"*|*"could not find credential"*|*"credentials were not found"*|*"authentication failed"*|*"unauthorized"*|*"forbidden"*|*"permission denied"*|*"401"*|*"403"*)
      printf 'repository_credentials_unavailable'
      ;;
    *)
      printf 'repository_unavailable'
      ;;
  esac
}

restore_repository_error_message() {
  case "$1" in
    repository_bootstrap_missing)
      printf '%s'         'recovery.env is missing RESTIC_REPOSITORY or RESTIC_PASSWORD; decrypt or regenerate the matching RecoveryKit'
      ;;
    repository_password_invalid)
      printf '%s'         'the restic repository password does not unlock this repository; use the RecoveryKit generated for this backup target'
      ;;
    repository_credentials_unavailable)
      printf '%s'         'the backup provider rejected or could not obtain repository credentials; restore the provider credentials from the matching RecoveryKit and verify their access'
      ;;
    *)
      printf '%s'         'the backup repository could not be opened; verify repository availability, network reachability, and RecoveryKit bootstrap credentials'
      ;;
  esac
}

report_restore_repository_error() {
  local code
  code="$(restore_repository_error_code "$1")"
  echo "restore diagnostic [$code]: $(restore_repository_error_message "$code")" >&2
}
