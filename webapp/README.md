# Local Tools Dashboard

A local web interface for all your `.py` scripts. Every tool gets its own
page — upload a file, click **Run**, watch the live log, and download the
output file when it's done. Everything runs on your own PC (`localhost`),
nothing is published to the internet.

## How to start (Windows)

1. Keep this whole `webapp` folder on your PC (you can open it with VS Code).
2. Open a terminal / the VS Code terminal and go to the folder:
   ```
   cd path\to\webapp
   ```
3. (Optional but good practice) create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   - If you want the **Product Image Scraper** tools to scrape sites like
     othoba.com / pickaboo.com, also install:
     ```
     pip install selenium
     ```
     and download a ChromeDriver matching your Chrome version, then add it
     to your PATH.
   - If you want to use **Custom Positioned Sticker / Price Insert** or
     **Top Deal Sticker Remover** (these only work on Windows + Photoshop):
     ```
     pip install pywin32
     ```
     and Photoshop needs to have been opened at least once.
   - If you want to use **Photoroom Lite** (AI background removal):
     ```
     pip install rembg scipy numpy
     ```
     The first run downloads an AI model (~170 MB), so it needs internet
     access once and takes longer than later runs.
5. Start the app:
   ```
   python app.py
   ```
6. Go to your browser: **http://localhost:5000**

To stop it, press `Ctrl+C` in the terminal.

## Starting it easily next time (Windows)

Once you've done the steps above the first time, you don't need to type
all the commands again every time you restart your PC — just double-click
**`start.bat`**. It automatically:
- activates the virtual environment (if one exists)
- starts the Flask app in its own window
- opens your browser to http://localhost:5000 after a few seconds

To stop the app, close the "Visual Team Console" window that pops up
(or press `Ctrl+C` inside it).

## Folder structure

```
webapp/
  app.py                  ← Flask app + all routes + tool registry
  processors/              ← refactored version of each .py script
    scraper.py              (from scrape_images.py)
    daraz_scraper.py         (from the Daraz 100% scrape_images.py)
    single_link_downloader.py
    multi_link_downloader.py
    original_ratio_downloader.py
    resizer.py               (from resize_images.py)
    photoroom_lite.py         (from batch_processor.py — AI background removal)
    price_insert.py          (from batch_price_insert_updated.py — Windows only)
    top_deal_sticker_remover.py (from photoshop_batch_crop.py — Windows only,
                              bundled template in assets/top_deal_sticker_remover/)
    common.py                shared helper functions
  templates/                HTML pages (landing, tool form, job/run page)
  static/style.css          design
  data/jobs/                every "Run" job's uploads + output land here
                             (good idea to keep this folder in .gitignore)
```

## How to add a new script

If you add more scripts later, each one needs these steps:

1. Create a new file in `processors/` (e.g. `my_new_tool.py`), with a
   `run(output_dir, log, **kwargs)` function that:
   - returns a list of output file paths when it's done
   - calls `log("...")` instead of `print()` (so it shows up live on the
     web page)
2. Add a new entry to the `TOOLS = {...}` dict near the top of `app.py` —
   name, description, which input fields it needs (file / files / number),
   and which module to use.

That's it — the new tool will show up as a card on the landing page, no
extra HTML needed. It reuses the same generic form + run page.

If you send me the remaining scripts, I can add them the same way.

## Important notes

- This is built to run only on your own PC (single-user, no login).
  You'd need to add authentication before exposing it to the internet.
- **Custom Positioned Sticker / Price Insert** and **Top Deal Sticker
  Remover** actually drive the real Adobe Photoshop app (via win32com) —
  so Photoshop will open while they run, and they depend on your PC. They
  can't be deployed to a cloud/server, only your own Windows PC.
- Running many files or many sticker/price-insert jobs at once can slow
  Photoshop down — it's better to run them one at a time.
