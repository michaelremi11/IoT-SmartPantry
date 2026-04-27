# Smart Pantry - Raspberry Pi Setup
By: Senior IoT Engineer

1. **Configure Firebase:**
   - Put your Firebase web config in `web/.env.local`.
   - Put `GOOGLE_APPLICATION_CREDENTIALS` and `FIREBASE_PROJECT_ID` in the project `.env` for the Pi hub and worker.
2. **Run Production Web:**
   - `npm run build`
   - `npm run start` (Production mode)
3. **Run Sensors:**
   - The Kivy hub starts `hub/sensors/sense_hat_logger.py` automatically and writes readings directly to Firestore.
   - `scripts/pi_client.py` is only for the legacy compatibility API.
4. **Run Firebase Worker:**
   - `uvicorn analytics.main:app --host 127.0.0.1 --port 8000`
5. **Kiosk Mode:**
   - Launch Chromium pointing to the web UI in full screen:
   - `chromium-browser --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://localhost:3000`
