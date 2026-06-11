# Setup & Getting Started Guide

This guide details the steps to set up, configure, and run the Pinterest Automation Tool (**PinBot**).

---

## Prerequisites

Before running the application, ensure you have the following installed:
1. **Python 3.11+**
2. **Redis** (used as Celery's message broker)
   ```bash
   sudo pacman -S redis
   ```
3. **Playwright Browsers** (used for TikTok scraping)

---

## Step 1: Install Dependencies

Set up a virtual environment and install the required packages:

```bash
# 1. Create a virtual environment
python -m venv .venv

# 2. Activate it
source .venv/bin/activate

# 3. Install packages in editable mode with development dependencies
pip install -e ".[dev]"

# 4. Install Playwright browser binaries
playwright install chromium
```

---

## Step 2: Configure Environment Variables

Open the local `.env` file in the root of the project and fill in your keys:

* **`GEMINI_API_KEY`**: Your Google AI Studio Gemini API key.
* **`GEMINI_MODEL`**: Set your desired model (e.g., `gemini-2.5-flash`, `gemini-2.0-flash-lite`, etc.).
* **`PINTEREST_APP_ID` & `PINTEREST_APP_SECRET`**: Obtained from your app on [developers.pinterest.com](https://developers.pinterest.com).
* **`REDIS_URL`**: Leave as `redis://localhost:6379/0` (standard default).

---

## Step 3: Start Services

You can start all required services (Redis, Celery worker + scheduler, and FastAPI) using a single command:

```bash
./start.sh
```

This script will:
1. Verify the virtual environment is present.
2. Check if Redis is running, and start a local daemonized instance if it isn't.
3. Start the Celery worker with the Beat scheduler enabled.
4. Launch the FastAPI/Uvicorn server.
5. Gracefully stop all services when you press `Ctrl+C`.

---

### Alternative: Manual/Separate Services (For debugging)

If you prefer to run services in separate terminals, you can do so:

#### Tab 1: Redis Server
```bash
sudo systemctl start redis
```

#### Tab 2: Celery Worker (with Beat)
```bash
source .venv/bin/activate
celery -A app.workers.celery_app worker -B --loglevel=info
```

#### Tab 3: FastAPI Web Server
```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## Step 4: Access the Dashboard

Once the servers are running:
1. Open your browser and navigate to **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.
2. Go to the **Settings** page and click **Connect Pinterest Account** to authenticate.
3. Once connected, select your target board.
4. Go back to the **Dashboard**, paste an Amazon affiliate link, and click **Process** to run the pipeline!

---

## Development & Testing

To run the automated test suite to ensure everything is working correctly:
```bash
source .venv/bin/activate
pytest
```
