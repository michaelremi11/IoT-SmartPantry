# Smart Pantry - Raspberry Pi Setup
By: Senior IoT Engineer

1. **Find Laptop IP:**
   - Run `python scripts/find_my_ip.py` (or `ipconfig` on Windows / `ifconfig` on Mac/Linux) on your host machine to get your local IPv4 address (e.g. 192.168.1.100).
2. **Set API URL on Pi:**
   - On the Pi, set the environment variable: `export NEXT_PUBLIC_API_URL=http://<YOUR_LAPTOP_IP>:8000` inside your `.env` or run config.
3. **Run Production Web:**
   - `npm run build`
   - `npm run start` (Production mode)
4. **Run Sensors:**
   - Start the hardware interaction script: `python hub/pi_client.py` 
5. **Kiosk Mode:**
   - Launch Chromium pointing to the web UI in full screen:
   - `chromium-browser --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://localhost:3000`
