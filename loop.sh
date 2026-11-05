#!/usr/bin/env bash
# يشغل البوت كل 15 دقيقة بدقة (على حدود الربع ساعة) لمدة LOOP_MINUTES دقيقة، من بعد كيسالي باش يتحفظ الـ state.
# الـ workflow كيعاود يشغلو بوحدو (تشغيل سلسلة). ما كيعتمدش على جدول GitHub.
BOT_CMD="${BOT_CMD:-python gold_bot.py}"
STEP="${STEP_SECONDS:-900}"
END=$(( $(date +%s) + ${LOOP_MINUTES:-50} * 60 ))
while :; do
  $BOT_CMD 2>&1 | tee -a bot_run.log || true
  now=$(date +%s)
  next=$(( (now / STEP + 1) * STEP + 20 ))     # الربع ساعة الجاية + 20 ثانية (باش الشمعة تتسد وتوصل داتا)
  [ "$next" -gt "$END" ] && break
  sleep $(( next - now ))
done
