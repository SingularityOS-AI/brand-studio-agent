import pytest
from playwright.sync_api import sync_playwright

@pytest.mark.e2e
def test_test_mode_bypass():
    """
    Test that in TEST_MODE, the frontend bypasses authentication
    using the test-mode-bypass token.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Enable console log capture
        console_messages = []
        page.on('console', lambda msg: console_messages.append(msg.text))

        # Navigate to the app
        print("[Test] Navigating to http://127.0.0.1:8010/")
        page.goto('http://127.0.0.1:8010/')

        # Wait for page to load and scripts to execute
        page.wait_for_load_state('networkidle', timeout=10000)

        # Wait a bit more for JS initialization
        page.wait_for_timeout(2000)

        # Take screenshot
        page.screenshot(path='C:/Users/gabri/Desktop/SINGULARITYOS/_PROYECTOS_SUELTOS_SIN_CLASIFICAR/hackaton lablab assemly IA voice agent/brand-studio-agent/test_screenshot.png', full_page=True)

        # Check console logs for TEST_MODE detection
        print("\n=== Console Logs ===")
        test_mode_found = False
        for log in console_messages:
            if 'TEST_MODE' in log:
                print(f"  {log}")
                test_mode_found = True

        if test_mode_found:
            print("\n✅ TEST_MODE detected in frontend")
        else:
            print("\n❌ TEST_MODE NOT detected - check /api/config response")

        # Check if login overlay is hidden
        login_overlay = page.locator('#Login-Overlay')
        main_app = page.locator('#Main-App')

        login_visible = login_overlay.is_visible()
        main_visible = main_app.is_visible()

        print(f"\n=== Visibility ===")
        print(f"Login Overlay visible: {login_visible}")
        print(f"Main App visible: {main_visible}")

        if not login_visible and main_visible:
            print("\n✅ Login bypassed - Main app is visible")
        elif login_visible:
            print("\n❌ Login overlay still visible - bypass NOT working")
        else:
            print("\n⚠️  Both hidden - page state unclear")

        # Check page title/content
        title = page.title()
        print(f"\n=== Page Info ===")
        print(f"Title: {title}")

        browser.close()

if __name__ == '__main__':
    test_test_mode_bypass()
