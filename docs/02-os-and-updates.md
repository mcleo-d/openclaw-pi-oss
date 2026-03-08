# OS Setup and Update Process

## Initial State (at start of project)

- **OS:** Raspberry Pi OS Lite 64-bit (Bookworm)
- **Kernel:** 6.12.47+rpt-rpi-2712
- **EEPROM:** 2025-12-08 (up to date)
- **SSH:** Active, password + key auth

## OS Update Performed (2026-02-26)

A full system upgrade was performed using:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
sudo apt autoclean
```

### Packages upgraded (36 total)

Notable upgrades:

| Package | Before | After |
|---|---|---|
| Kernel | 6.12.47+rpt | 6.12.62+rpt |
| OpenSSL / libssl3 | 3.0.17 | 3.0.18 |
| sudo | 1.9.13p3-1+deb12u2 | 1.9.13p3-1+deb12u3 |
| bash | 5.2.15-2+b9 | 5.2.15-2+b10 |
| rsync | 3.2.7-1+deb12u2 | 3.2.7-1+deb12u4 |
| rpi-eeprom | 28.7 | 28.13 |
| gnupg suite | 2.2.40-1.1+deb12u1 | 2.2.40-1.1+deb12u2 |

A reboot was performed to load the new kernel. Post-reboot kernel confirmed as `6.12.62+rpt-rpi-2712`.

## EEPROM Firmware

Checked with `sudo rpi-eeprom-update`. Status at time of check:

```text
BOOTLOADER: up to date
   CURRENT: Mon  8 Dec 19:29:54 UTC 2025 (1765222194)
    LATEST: Mon  8 Dec 19:29:54 UTC 2025 (1765222194)
   RELEASE: default
```

No EEPROM update was required.

## Ongoing Updates

Automatic security updates are configured via `unattended-upgrades`:

- Security channel: `${distro_id}:${distro_codename}-security`
- Raspberry Pi channel: `Raspberry Pi Foundation:${distro_codename}`
- Automatic reboot: **disabled** (manual reboot required after kernel updates)
- Cleanup: unused dependencies removed automatically

Config files:

- `/etc/apt/apt.conf.d/50unattended-upgrades`
- `/etc/apt/apt.conf.d/20auto-upgrades`

### Manual update process

```bash
# Check for updates
ssh <hostname> "sudo apt update"

# Apply updates
ssh <hostname> "sudo apt full-upgrade -y"

# Check if reboot is needed
ssh <hostname> "[ -f /var/run/reboot-required ] && echo 'Reboot required' || echo 'No reboot needed'"

# Reboot if needed
ssh <hostname> "sudo reboot"
# Wait ~30s then reconnect to verify new kernel
ssh <hostname> "uname -r"
```

### Check EEPROM

```bash
ssh <hostname> "sudo rpi-eeprom-update"
```
