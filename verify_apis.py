from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    # Track API requests
    api_results = []

    def handle_response(response):
        if '/api/' in response.url:
            status = response.status
            url = response.url
            if status == 200:
                api_results.append(f"OK: {url.split('/api/')[-1]}")
            elif status == 401:
                api_results.append(f"FAIL 401: {url.split('/api/')[-1]}")
            elif status == 402:
                api_results.append(f"PAYWALL 402: {url.split('/api/')[-1]}")
            else:
                api_results.append(f"STATUS {status}: {url.split('/api/')[-1]}")

    page.on('response', handle_response)

    print("Navigating to app...")
    page.goto('http://127.0.0.1:8010/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)

    print("\nAPI calls detected:")
    if api_results:
        for result in api_results:
            print(f"  {result}")
    else:
        print("  (none - waiting for initial load)")

    # Check page content
    credits_text = page.locator('.credits-display').text_content() or 'not found'
    print(f"\nCredits display: {credits_text.strip()[:50]}")

    # Try clicking something to trigger more API calls
    try:
        buttons = page.locator('button').all()
        if buttons:
            print(f"\nFound {len(buttons)} buttons - clicking first to test interaction...")
            buttons[0].click()
            page.wait_for_timeout(1000)
    except Exception as e:
        print(f"\nCould not click: {e}")

    print("\nFinal API status:")
    success_count = sum(1 for r in api_results if r.startswith('OK'))
    fail_count = sum(1 for r in api_results if 'FAIL' in r)
    print(f"  Success: {success_count}")
    print(f"  Failed (401): {fail_count}")

    if fail_count == 0 and success_count > 0:
        print("\nPASS: APIs working without 401 errors")
    else:
        print("\nFAIL: Detected 401 errors or no successful calls")

    browser.close()
