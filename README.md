# Heltec & MeshCore Projects

ESPHome configurations, Halo TCP proxy, and NINA monitor for the ProPott home automation setup.

## Structure

- **esphome-local/** — ESPHome configs developed locally (Heltec V4, T-Display-S3)
- **esphome-ha/** — ESPHome configs stored on HA server (e-paper panel, MeshCore XIAO, mmWave)
- **halo-proxy/** — Halo sensor TCP proxy (listens on port 9999, forwards to HA + MeshCore)
- **nina/** — NINA civil warning monitor (polls NINA API, sends to MeshCore channels)

## Devices

| File | Device | Purpose |
|------|--------|---------|
| heltec-v4-display.yaml | Heltec V4 | Main LVGL touch display, NINA + Halo pages |
| heltec-v4-halo-nina.yaml | Heltec V4 | Halo sensor + NINA combined display |
| t_display_s3_nina.yaml | T-Display-S3 | NINA warning dashboard |
| t_display_s3_halo.yaml | T-Display-S3 | Halo sensor display |
| epaper-panel.yaml | E-Paper panel | Status display |
| meshcore-xiao.yaml | Seeed XIAO | MeshCore panic button |
| seeedstudio-mr60fda2.yaml | MR60FDA2 | mmWave presence sensor |
