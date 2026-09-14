from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    console_messages = []
    page.on('console', lambda msg: console_messages.append(msg.text))

    print("Navigating to http://127.0.0.1:8010/")
    page.goto('http://127.0.0.1:8010/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)

    print("Console logs:")
    test_mode_found = any('TEST_MODE' in log for log in console_messages)
    if test_mode_found:
        print("  -> TEST_MODE detected")

    login_visible = page.locator('#Login-Overlay').is_visible()
    main_visible = page.locator('#Main-App').is_visible()

    print(f"\nLogin Overlay visible: {login_visible}")
    print(f"Main App visible: {main_visible}")

    if not login_visible and main_visible:
        print("\nPASS: Login bypassed successfully")
    else:
        print("\nFAIL: Login bypass not working")

    browser.close()
