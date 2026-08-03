#!/bin/sh
# Run this ON THE BOARD as root. Adds 512 MB of swap so an allocation spike
# stalls instead of killing a process. Swap lives on the SD card and is slow -
# that is the point: slow beats dead.
set -e
if [ -f /swapfile ]; then echo "/swapfile already exists"; swapon --show; exit 0; fi
echo "creating /swapfile (512 MB) - takes a minute on SD"
dd if=/dev/zero of=/swapfile bs=1M count=512 status=none
chmod 600 /swapfile
mkswap /swapfile >/dev/null
swapon /swapfile
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo "done - swap is on and will persist across reboots:"
free -m
echo
echo "optional, reduces SD wear by swapping only under real pressure:"
echo "  sysctl vm.swappiness=10"
echo "  echo 'vm.swappiness=10' >> /etc/sysctl.conf"
