#!/bin/bash
# 在云端模拟器里装 APK、启动、连续截图、抓日志(由 GitHub Actions 的 emulator-runner 调用)
APK="$1"
mkdir -p out
adb shell input keyevent 82 || true
adb install -r "$APK"
adb logcat -c
adb shell am start -n com.shouxi.app/.MainActivity --es route pool --ez selftest true
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  sleep 5
  adb exec-out screencap -p > out/s_$(printf %02d $i).png
  echo "t+$((i*5))s pid=$(adb shell pidof com.shouxi.app)"
  adb logcat -d -s ShouxiPage:I ShouxiTest:I ShouxiJS:I Shouxi:E "*:S" > out/log_key.txt
  tail -4 out/log_key.txt | cut -c1-300
done
adb logcat -d > out/logcat.txt
echo "==== ShouxiPage / ShouxiTest / errors ===="
grep -E "ShouxiPage|ShouxiTest|启动失败|AndroidRuntime" out/logcat.txt | cut -c1-400 | tail -20
