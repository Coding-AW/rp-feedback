#!/bin/sh
# Run this ON THE BOARD, over SSH. Read-only: it changes nothing.
echo "=== memory ==============================================="
free -m
echo
echo "=== what Linux was given (the capture region is carved out here) ==="
cat /proc/cmdline
echo
grep -E 'MemTotal|MemFree|MemAvailable|Committed_AS|CommitLimit|SwapTotal' /proc/meminfo
echo
echo "=== overcommit policy (2 = strict; fork fails early under it) ==="
cat /proc/sys/vm/overcommit_memory
echo
echo "=== biggest processes ===================================="
ps -eo pid,ppid,rss,etime,comm --sort=-rss | head -12
echo
echo "=== how many kernels are alive? one per open notebook ===="
ps -ef | grep -c '[i]pykernel'
ps -eo pid,rss,etime,args --sort=-rss | grep '[i]pykernel'
echo
echo "=== file descriptors held by each kernel ================="
for p in $(pgrep -f ipykernel); do
  echo "  pid $p: $(ls /proc/$p/fd 2>/dev/null | wc -l) fds, \
$(grep -c . /proc/$p/maps 2>/dev/null) mappings"
done
