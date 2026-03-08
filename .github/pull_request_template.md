## Summary

<!-- Describe what this PR changes and why. -->

## Checklist

- [ ] No real values introduced — no hostnames, IP addresses, credentials, or numeric security thresholds
- [ ] No injection patterns added to `proxy.py` (patterns belong in `patterns.conf` on the target system)
- [ ] All new `proxy.py` tunables use the `PROXY_` prefix and `os.environ.get()`
- [ ] `config/README.md` file map updated if config files were added or removed
- [ ] New sensitive files added to `.gitignore` with a `.template` equivalent provided
- [ ] `detect-secrets` baseline passes: `detect-secrets scan --baseline .secrets.baseline && git diff --exit-code .secrets.baseline`

## Testing

<!-- How was this tested? If Pi hardware was used, include model and OS version. -->
<!-- Documentation-only changes: state that no hardware testing is required. -->

## Related issues

<!-- Link any related issues: Closes #N, Related to #N -->
