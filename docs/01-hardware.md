# Hardware & Connectivity Reference

## Device

| Property | Value |
|---|---|
| Hardware | Raspberry Pi 5 |
| RAM | 8GB |
| Storage | microSD (117GB total, ~109GB free after OS) |
| OS | Raspberry Pi OS Lite 64-bit (Bookworm / Debian 12) |
| Kernel | 6.12.62+rpt-rpi-2712 (aarch64) |
| Architecture | ARM Cortex-A76, aarch64 |
| Hostname | `<hostname>` |
| mDNS name | `<hostname>.local` (via avahi-daemon) |
| Network | Ethernet (eth0) + WiFi available |
| Mode | Headless — no display, SSH only |

## Network Access

The Pi is accessible on the local network at `<hostname>.local` via mDNS (avahi-daemon). This resolves to its current LAN IP automatically without needing to know the IP address.

```bash
# Connect via SSH (key-based auth only)
ssh <hostname>

# Ping
ping <hostname>.local
```

## SSH Key Setup (already configured)

The Mac's SSH public key (`~/.ssh/id_ed25519.pub`) is installed in `/home/<username>/.ssh/authorized_keys` on the Pi. Password authentication is disabled.

If SSH keys ever need to be re-established:
```bash
# From the Mac (requires password auth to be temporarily re-enabled on Pi)
ssh-copy-id -i ~/.ssh/id_ed25519.pub <username>@<hostname>.local
```

Or manually paste the public key into `~/.ssh/authorized_keys` on the Pi:
```bash
# On the Pi:
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<public key here>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## Resource Summary

| Resource | Total | Used | Available |
|---|---|---|---|
| RAM | 7.9GB | ~236MB (OS only) | ~7.6GB |
| Disk | 117GB | 2.3GB | ~109GB |
| Swap | 511MB | 0 | 511MB |

The Pi 5 (8GB) comfortably meets all requirements:
- OpenClaw Docker container: ~2GB RAM allocated limit
- Ollama + 3B parameter model: ~2-3GB RAM
- OS overhead: ~300MB
- Remaining headroom: ~2-3GB
