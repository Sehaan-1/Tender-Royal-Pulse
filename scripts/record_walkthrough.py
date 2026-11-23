"""Walkthrough video & GIF generator for TenderPulse.

Records headless browser interactions using Playwright and converts the resulting
video to an optimized MP4 and animated GIF using ffmpeg.
"""

import asyncio
import os
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT_DIR = Path("assets")
TEMP_VIDEO_DIR = Path("temp_recordings")

CURSOR_JS = """
(() => {
    const cursor = document.createElement('div');
    cursor.id = 'recording-mouse-pointer';
    cursor.style.cssText = `
        position: fixed;
        width: 20px;
        height: 20px;
        background: rgba(16, 185, 129, 0.85);
        border: 2px solid #ffffff;
        border-radius: 50%;
        pointer-events: none;
        z-index: 999999;
        transform: translate(-50%, -50%);
        transition: transform 0.08s ease, width 0.15s ease, height 0.15s ease, background 0.15s ease;
        box-shadow: 0 0 12px rgba(16, 185, 129, 0.7);
    `;
    document.body.appendChild(cursor);

    window.addEventListener('mousemove', (e) => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
    });

    window.addEventListener('mousedown', () => {
        cursor.style.transform = 'translate(-50%, -50%) scale(0.75)';
        cursor.style.background = 'rgba(52, 211, 153, 1)';
    });

    window.addEventListener('mouseup', () => {
        cursor.style.transform = 'translate(-50%, -50%) scale(1)';
        cursor.style.background = 'rgba(16, 185, 129, 0.85)';
    });
})();
"""


async def smooth_move(page, target_x: float, target_y: float, steps: int = 18):
    await page.mouse.move(target_x, target_y, steps=steps)


async def record():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    url = "https://tender-royal-pulse.vercel.app"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(TEMP_VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")
        await page.evaluate(CURSOR_JS)
        await asyncio.sleep(1.5)

        # 1. Hover KPI stat cards
        print("Showcasing KPI cards...")
        await smooth_move(page, 200, 160)
        await asyncio.sleep(0.8)
        await smooth_move(page, 480, 160)
        await asyncio.sleep(0.8)
        await smooth_move(page, 760, 160)
        await asyncio.sleep(0.8)

        # 2. Search for "Hospital"
        print("Typing search query...")
        search_box = page.locator("#search-input")
        box = await search_box.bounding_box()
        if box:
            await smooth_move(page, box["x"] + 100, box["y"] + box["height"] / 2)
            await page.mouse.click(box["x"] + 100, box["y"] + box["height"] / 2)
            await page.keyboard.type("Hospital", delay=120)
            await asyncio.sleep(1.5)

        # 3. Open Detail Modal
        print("Opening tender detail modal...")
        first_view_btn = page.locator("tbody tr button").first
        if await first_view_btn.count() > 0:
            v_box = await first_view_btn.bounding_box()
            if v_box:
                await smooth_move(page, v_box["x"] + v_box["width"] / 2, v_box["y"] + v_box["height"] / 2)
                await page.mouse.click(v_box["x"] + v_box["width"] / 2, v_box["y"] + v_box["height"] / 2)
                await asyncio.sleep(2.0)

                # Scroll modal content
                modal_body = page.locator("#modal-content")
                if await modal_body.count() > 0:
                    m_box = await modal_body.bounding_box()
                    if m_box:
                        await smooth_move(page, m_box["x"] + m_box["width"] / 2, m_box["y"] + 200)
                        await page.mouse.wheel(0, 300)
                        await asyncio.sleep(1.5)
                        await page.mouse.wheel(0, -300)
                        await asyncio.sleep(0.8)

                # Close modal
                close_btn = page.locator("#tender-modal button[onclick*='closeModal']")
                if await close_btn.count() > 0:
                    c_box = await close_btn.bounding_box()
                    if c_box:
                        await smooth_move(page, c_box["x"] + c_box["width"] / 2, c_box["y"] + c_box["height"] / 2)
                        await page.mouse.click(c_box["x"] + c_box["width"] / 2, c_box["y"] + c_box["height"] / 2)
                        await asyncio.sleep(1.2)

        # 4. Clear search & change category filter
        print("Filtering by category...")
        if box:
            await smooth_move(page, box["x"] + 100, box["y"] + box["height"] / 2)
            await page.mouse.click(box["x"] + 100, box["y"] + box["height"] / 2)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.0)

        # 5. Switch to Runs & Queue State Tab
        print("Switching to Runs tab...")
        runs_tab = page.locator("#tab-btn-runs")
        if await runs_tab.count() > 0:
            r_box = await runs_tab.bounding_box()
            if r_box:
                await smooth_move(page, r_box["x"] + r_box["width"] / 2, r_box["y"] + r_box["height"] / 2)
                await page.mouse.click(r_box["x"] + r_box["width"] / 2, r_box["y"] + r_box["height"] / 2)
                await asyncio.sleep(2.0)

        # 6. Switch to Category Breakdown Tab
        print("Switching to Analytics tab...")
        analytics_tab = page.locator("#tab-btn-analytics")
        if await analytics_tab.count() > 0:
            a_box = await analytics_tab.bounding_box()
            if a_box:
                await smooth_move(page, a_box["x"] + a_box["width"] / 2, a_box["y"] + a_box["height"] / 2)
                await page.mouse.click(a_box["x"] + a_box["width"] / 2, a_box["y"] + a_box["height"] / 2)
                await asyncio.sleep(2.0)

        # 7. Switch back to Tenders Tab
        print("Returning to Tenders tab...")
        tenders_tab = page.locator("#tab-btn-tenders")
        if await tenders_tab.count() > 0:
            t_box = await tenders_tab.bounding_box()
            if t_box:
                await smooth_move(page, t_box["x"] + t_box["width"] / 2, t_box["y"] + t_box["height"] / 2)
                await page.mouse.click(t_box["x"] + t_box["width"] / 2, t_box["y"] + t_box["height"] / 2)
                await asyncio.sleep(1.2)

        # 8. Showcase "New Crawl" modal
        print("Opening New Crawl modal...")
        new_crawl_btn = page.locator("header button:has-text('New Crawl')")
        if await new_crawl_btn.count() > 0:
            nc_box = await new_crawl_btn.bounding_box()
            if nc_box:
                await smooth_move(page, nc_box["x"] + nc_box["width"] / 2, nc_box["y"] + nc_box["height"] / 2)
                await page.mouse.click(nc_box["x"] + nc_box["width"] / 2, nc_box["y"] + nc_box["height"] / 2)
                await asyncio.sleep(1.8)

                # Close modal
                cancel_btn = page.locator("#crawl-modal button:has-text('Cancel')")
                if await cancel_btn.count() > 0:
                    cn_box = await cancel_btn.bounding_box()
                    if cn_box:
                        await smooth_move(page, cn_box["x"] + cn_box["width"] / 2, cn_box["y"] + cn_box["height"] / 2)
                        await page.mouse.click(cn_box["x"] + cn_box["width"] / 2, cn_box["y"] + cn_box["height"] / 2)
                        await asyncio.sleep(1.2)

        # 9. Hover export buttons
        print("Hovering Export buttons...")
        export_btn = page.locator("header button:has-text('Export CSV')")
        if await export_btn.count() > 0:
            e_box = await export_btn.bounding_box()
            if e_box:
                await smooth_move(page, e_box["x"] + e_box["width"] / 2, e_box["y"] + e_box["height"] / 2)
                await asyncio.sleep(1.0)

        await asyncio.sleep(1.5)
        video_path = await page.video.path()
        await context.close()
        await browser.close()
        print(f"Recorded video saved to: {video_path}")
        return video_path


def convert_video(source_webm: str):
    ffmpeg_exe = r"C:\Users\INDIA TECHNOLOGY\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
    if not os.path.exists(ffmpeg_exe):
        ffmpeg_exe = "ffmpeg"

    mp4_out = OUTPUT_DIR / "demo.mp4"
    gif_out = OUTPUT_DIR / "demo.gif"
    poster_out = OUTPUT_DIR / "demo-poster.png"

    print("Converting to MP4...")
    # Convert webm to optimized H.264 MP4 with faststart
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            source_webm,
            "-c:v",
            "libx264",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "slow",
            "-crf",
            "22",
            "-movflags",
            "+faststart",
            str(mp4_out),
        ],
        check=True,
    )

    print("Generating poster screenshot...")
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-ss",
            "00:00:02",
            "-i",
            str(mp4_out),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(poster_out),
        ],
        check=True,
    )

    print("Converting to high-quality animated GIF with palettegen...")
    # Generate high quality GIF using 2-pass palettegen, scaled to 960 width and 15 fps
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            str(mp4_out),
            "-filter_complex",
            "[0:v] fps=15,scale=960:-1:flags=lanczos,split [a][b];[a] palettegen=max_colors=128:stats_mode=diff [p];[b][p] paletteuse=dither=bayer:bayer_scale=3",
            str(gif_out),
        ],
        check=True,
    )

    print("Artifacts generated:")
    print(f"  - MP4: {mp4_out} ({mp4_out.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  - GIF: {gif_out} ({gif_out.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  - Poster: {poster_out}")


if __name__ == "__main__":
    recorded_path = asyncio.run(record())
    if recorded_path:
        convert_video(recorded_path)
