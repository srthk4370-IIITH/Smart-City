while pgrep -f "qai-hub-models" >/dev/null; do sleep 20; done
grep -v -E "Uploading|%\|" ~/qaihm_work/ft_export.log | tail -12
ls -la ~/qaihm_work/ft_genie/*/ 2>/dev/null | head -14
