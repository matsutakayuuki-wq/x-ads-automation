"""X Ads Editor ブラウザアップロード（Playwright）"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("data/browser_sessions")

# Playwright bot検出回避用スクリプト
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""


class BrowserSessionError(Exception):
    pass


class SessionExpiredError(BrowserSessionError):
    pass


class XAdsEditorUploader:
    """X Ads Editor へのExcelアップロード自動化"""

    def __init__(self, credential_id: int):
        self.credential_id = credential_id
        self.session_dir = SESSIONS_DIR / str(credential_id)
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def session_exists(self) -> bool:
        return (self.session_dir / "state.json").exists()

    async def _ensure_session_dir(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)

    async def launch_for_login(self) -> None:
        """ログイン用にブラウザを起動（ヘッド付き）"""
        await self._ensure_session_dir()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            storage_state=str(self.session_dir / "state.json")
            if self.session_exists else None,
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        self._page = await self._context.new_page()
        await self._page.goto("https://ads.x.com/")

    async def save_session(self) -> None:
        """現在のブラウザコンテキストのセッションを保存"""
        if self._context:
            await self._context.storage_state(
                path=str(self.session_dir / "state.json")
            )
            logger.info("Session saved for credential %d", self.credential_id)

    async def check_session_valid(self) -> bool:
        """保存済みセッションが有効か確認"""
        if not self.session_exists:
            return False
        pw = None
        browser = None
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                storage_state=str(self.session_dir / "state.json"),
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            await ctx.add_init_script(_STEALTH_SCRIPT)
            page = await ctx.new_page()
            await page.goto("https://ads.x.com/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            is_valid = "login" not in page.url.lower() and "oauth" not in page.url.lower()
            return is_valid
        except Exception as e:
            logger.warning("Session check failed: %s", e)
            return False
        finally:
            if browser:
                await browser.close()
            if pw:
                await pw.stop()

    async def upload_excel(
        self,
        excel_path: str,
        ads_account_id: str,
    ) -> dict:
        """Excelファイルをアップロードし結果を返す"""
        if not self.session_exists:
            raise BrowserSessionError("No saved session. Login required.")

        await self._ensure_session_dir()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            storage_state=str(self.session_dir / "state.json"),
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        await self._context.add_init_script(_STEALTH_SCRIPT)
        self._page = await self._context.new_page()

        try:
            result = await self._do_upload(excel_path, ads_account_id)
            await self.save_session()
            return result
        except SessionExpiredError:
            raise
        except Exception as e:
            ss_path = str(self.session_dir / "error_screenshot.png")
            try:
                await self._page.screenshot(path=ss_path)
            except Exception:
                ss_path = None
            logger.error("Upload failed: %s", e, exc_info=True)
            raise BrowserSessionError(f"Upload failed: {e}") from e
        finally:
            await self.close()

    async def _do_upload(self, excel_path: str, ads_account_id: str) -> dict:
        """実際のアップロードフロー"""
        page = self._page

        # Step 1: Ads Editor ページに直接遷移
        editor_url = f"https://ads.x.com/accounts/{ads_account_id}/power_tools/editor"
        logger.info("Navigating to Ads Editor: %s", editor_url)
        await page.goto(editor_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # ログインチェック + ページ到達確認
        current_url = page.url
        logger.info("Current URL after navigation: %s", current_url)
        if "login" in current_url.lower() or "oauth" in current_url.lower():
            raise SessionExpiredError("Session expired. Re-login required.")

        # 404 / エラーページ検出
        title = await page.title()
        logger.info("Page title: %s", title)
        page_content = await page.content()
        if "表示する内容がありません" in page_content or "このページは存在しません" in page_content:
            ss_path = str(self.session_dir / "navigation_error.png")
            await page.screenshot(path=ss_path)
            raise BrowserSessionError(
                f"Ads Editor page not accessible (404). URL: {current_url}, Title: {title}"
            )

        # Step 2: Import タブをクリック
        import_tab = page.locator(".PowerEditorTabGroup-Tab", has_text="インポート").or_(
            page.locator(".PowerEditorTabGroup-Tab", has_text="Import")
        ).first
        await import_tab.wait_for(timeout=15000)
        await import_tab.click()
        logger.info("Import tab clicked")
        await page.wait_for_timeout(1000)

        # Step 3: ファイルアップロード（hidden input に直接セット）
        file_input = page.locator("#PowerEditorUploader-fileSelect")
        await file_input.wait_for(state="attached", timeout=10000)
        await file_input.set_input_files(excel_path)
        logger.info("Excel file set: %s", excel_path)

        # Step 4: 「アップロードとプレビュー」ボタンが有効になるのを待ってクリック
        preview_btn = page.locator("#PowerEditorUploader-previewSubmit")
        await preview_btn.wait_for(timeout=10000)
        await page.wait_for_function(
            "document.getElementById('PowerEditorUploader-previewSubmit')?.disabled === false",
            timeout=10000,
        )

        await preview_btn.click()
        logger.info("Upload and Preview button clicked")

        # Step 5: バリデーション結果を待つ
        # 戦略: 成功メッセージだけを待つ。エラーは成功が来ない場合にのみ確認する。
        # これにより、前回のエラーメッセージが残っている場合の誤検知を完全に回避する。
        success_locator = page.locator("text=認証に成功しました").or_(
            page.locator("text=Validation successful")
        ).first

        try:
            await success_locator.wait_for(timeout=120000)
            logger.info("Validation successful message appeared")
        except Exception:
            # タイムアウト: 成功メッセージが表示されなかった
            ss_path = str(self.session_dir / "validation_error_screenshot.png")
            await page.screenshot(path=ss_path)
            page_text = await page.inner_text("body")
            logger.error("Validation failed or timed out. Page text: %s", page_text[:500])

            # エラー詳細をページから抽出
            error_detail = ""
            if "ファイルにエラーがあります" in page_text or "file has errors" in page_text.lower():
                try:
                    detail_el = page.locator("table").first
                    if await detail_el.is_visible():
                        error_detail = await detail_el.inner_text()
                except Exception:
                    pass
                return {
                    "success": False,
                    "message": f"Validation error: {error_detail[:200] or 'Check screenshot.'}",
                    "screenshot_path": ss_path,
                }
            else:
                return {
                    "success": False,
                    "message": "Preview timed out (120s). Check screenshot.",
                    "screenshot_path": ss_path,
                }

        await page.wait_for_timeout(1000)

        # Step 6: 「変更を適用」ボタンをクリック
        apply_btn = page.locator("#PowerEditorUploader-applySubmit")
        await apply_btn.click()
        logger.info("Apply Changes button clicked")

        # Step 7: 適用完了を待つ
        await page.wait_for_timeout(15000)

        # 結果スクリーンショット
        ss_path = str(self.session_dir / "result_screenshot.png")
        await page.screenshot(path=ss_path)

        return {
            "success": True,
            "message": "Upload completed. Check screenshot for details.",
            "screenshot_path": ss_path,
        }

    # ------------------------------------------------------------------
    # ポスト作成（広告マネージャーのComposer画面を使用）
    # ------------------------------------------------------------------

    async def create_posts_batch(
        self,
        ads_account_id: str,
        posts: list[dict],
    ) -> list[dict]:
        """複数のポストを1つのブラウザセッションで作成する。

        Args:
            ads_account_id: 広告アカウントID
            posts: [{"tweet_text": str, "media_file_paths": list|None,
                     "ad_name": str, "website_url": str}, ...]
        Returns:
            [{"success": bool, "tweet_id": str|None, "message": str}, ...]
        """
        if not self.session_exists:
            raise BrowserSessionError("No saved session. Login required.")

        await self._ensure_session_dir()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            storage_state=str(self.session_dir / "state.json"),
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        await self._context.add_init_script(_STEALTH_SCRIPT)
        self._page = await self._context.new_page()

        results = []
        try:
            for i, post in enumerate(posts):
                logger.info("Creating post %d/%d", i + 1, len(posts))
                try:
                    result = await self._do_create_post(
                        ads_account_id,
                        tweet_text=post["tweet_text"],
                        media_file_paths=post.get("media_file_paths"),
                        ad_name=post.get("ad_name", ""),
                        website_url=post.get("website_url", ""),
                    )
                    results.append(result)
                except SessionExpiredError:
                    raise
                except Exception as e:
                    ss_path = str(self.session_dir / f"create_post_error_{i}.png")
                    try:
                        await self._page.screenshot(path=ss_path)
                    except Exception:
                        pass
                    logger.error("Post %d creation failed: %s", i + 1, e, exc_info=True)
                    results.append({
                        "success": False,
                        "tweet_id": None,
                        "message": f"Post creation failed: {e}",
                    })

            await self.save_session()
            return results
        except SessionExpiredError:
            raise
        finally:
            await self.close()

    async def create_post(
        self,
        ads_account_id: str,
        tweet_text: str,
        media_file_paths: list[str] | None = None,
        ad_name: str = "",
        website_url: str = "",
    ) -> dict:
        """広告マネージャーの作成画面でダークポストを作成し、ポストIDを返す。

        Returns: {"success": bool, "tweet_id": str|None, "message": str}
        """
        if not self.session_exists:
            raise BrowserSessionError("No saved session. Login required.")

        await self._ensure_session_dir()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            storage_state=str(self.session_dir / "state.json"),
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        await self._context.add_init_script(_STEALTH_SCRIPT)
        self._page = await self._context.new_page()

        try:
            result = await self._do_create_post(
                ads_account_id, tweet_text, media_file_paths, ad_name,
                website_url,
            )
            await self.save_session()
            return result
        except SessionExpiredError:
            raise
        except Exception as e:
            ss_path = str(self.session_dir / "create_post_error.png")
            try:
                await self._page.screenshot(path=ss_path)
            except Exception:
                pass
            logger.error("Post creation failed: %s", e, exc_info=True)
            raise BrowserSessionError(f"Post creation failed: {e}") from e
        finally:
            await self.close()

    async def _do_create_post(
        self,
        ads_account_id: str,
        tweet_text: str,
        media_file_paths: list[str] | None,
        ad_name: str,
        website_url: str = "",
    ) -> dict:
        """広告マネージャー Composer を操作してポストを作成"""
        import re

        page = self._page

        # Step 1: Composer ページに遷移（リトライ付き）
        composer_url = f"https://ads.x.com/composer/{ads_account_id}/carousel"
        composer_loaded = False

        for attempt in range(3):
            logger.info("Navigating to Composer (attempt %d/3): %s", attempt + 1, composer_url)
            await page.goto(composer_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            current_url = page.url
            if "login" in current_url.lower() or "oauth" in current_url.lower():
                raise SessionExpiredError("Session expired. Re-login required.")

            # Composer の UI 要素が表示されるのを待つ
            # NOTE: text= と CSS セレクタはカンマで混ぜられない（Playwright仕様）
            #       → locator().or_() を使う
            try:
                composer_locator = page.locator("text=作成画面").or_(
                    page.locator("[contenteditable='true']")
                ).or_(
                    page.locator(".TweetTextInput-editor")
                )
                await composer_locator.first.wait_for(timeout=20000)
                composer_loaded = True
                logger.info("Composer page loaded (attempt %d)", attempt + 1)
                break
            except Exception:
                ss_path = str(self.session_dir / f"composer_load_fail_{attempt}.png")
                await page.screenshot(path=ss_path)
                logger.warning(
                    "Composer not loaded (attempt %d), screenshot: %s. URL: %s",
                    attempt + 1, ss_path, page.url,
                )
                if attempt < 2:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)

        if not composer_loaded:
            raise BrowserSessionError(
                "Composer page failed to load after 3 attempts. "
                f"Current URL: {page.url}"
            )

        # Step 2: 広告名を入力（オプション）
        if ad_name:
            # 「名前」フィールド: 最初の input 要素
            name_input = page.locator("input").first
            try:
                await name_input.wait_for(timeout=5000)
                await name_input.fill(ad_name)
                logger.info("Ad name set: %s", ad_name)
            except Exception:
                logger.warning("Name input not found, skipping")

        # Step 3: 投稿文を入力
        # Composer のテキストエリアは contenteditable div
        # role="textbox" または data-testid で探す
        text_area = page.locator(
            '[role="textbox"]'
        ).or_(
            page.locator('[contenteditable="true"]')
        ).or_(
            page.locator('[data-placeholder="いまどうしてる？"]')
        ).first
        await text_area.wait_for(timeout=10000)
        await text_area.click()
        await page.wait_for_timeout(500)
        # contenteditable div にはキーボード入力で入力
        await page.keyboard.type(tweet_text, delay=20)
        logger.info("Tweet text entered (%d chars)", len(tweet_text))

        # Step 3.5: ランディングページ（ウェブサイト）を設定
        # 「Website Card を使用」が有効な場合（website_url が明示的に設定されている場合）のみ
        # 「ウェブサイト」を選択してカードを作成する。
        # チェックが入っていない場合はランディングページを選択せず、そのままポストする。
        lp_url = website_url  # campaign.website_card_url から渡される

        if lp_url and media_file_paths:
            try:
                website_card = page.locator("text=ウェブサイト").first
                await website_card.scroll_into_view_if_needed()
                await website_card.click()
                logger.info("Website landing page card clicked")
                await page.wait_for_timeout(1500)
            except Exception as e:
                logger.warning("Website card click failed: %s", e)

        # Step 4: メディアアップロード（ファイルがある場合）
        if media_file_paths:
            # 「単一メディア」カードをクリック
            single_media = page.locator("text=単一メディア").or_(
                page.locator("text=Single media")
            ).first
            try:
                await single_media.scroll_into_view_if_needed()
                await single_media.click()
                logger.info("Single media option selected")
            except Exception as e:
                logger.warning("Single media click failed: %s", e)
            await page.wait_for_timeout(1000)

            # メディア追加方法: file input を直接探す（ダイアログ不要）
            # まず「メディアを追加」ボタンを探す
            add_media_btn = page.locator(
                "button", has_text="メディアを追加"
            ).or_(
                page.locator("button", has_text="Add media")
            ).first
            try:
                await add_media_btn.wait_for(timeout=5000)
                await add_media_btn.click()
                logger.info("Add media button clicked")
                await page.wait_for_timeout(2000)
            except Exception:
                logger.info("Add media button not visible, looking for file input directly")

            # ファイルアップロード（file input に直接セット）
            file_input = page.locator(
                '.FilePicker-callToActionFileInput'
            ).or_(
                page.locator('input[type="file"]')
            ).first
            try:
                await file_input.wait_for(state="attached", timeout=10000)
                await file_input.set_input_files(media_file_paths[0])
                logger.info("Media file set: %s", media_file_paths[0])
            except Exception as e:
                ss_path = str(self.session_dir / "media_file_input_error.png")
                await page.screenshot(path=ss_path)
                logger.error("File input failed: %s (screenshot: %s)", e, ss_path)
                # メディアなしで続行
                media_file_paths = None

            if media_file_paths:
                # アップロード完了を待つ
                await page.wait_for_timeout(5000)

                # 「確認」ボタンをクリック
                confirm_btn = page.locator(
                    "button", has_text="確認"
                ).or_(
                    page.locator("button", has_text="Confirm")
                ).first
                try:
                    await confirm_btn.wait_for(timeout=30000)
                    await confirm_btn.click()
                    logger.info("Media confirm button clicked")
                except Exception:
                    ss_path = str(self.session_dir / "media_upload_state.png")
                    await page.screenshot(path=ss_path)
                    logger.warning(
                        "Confirm button not found, check: %s", ss_path
                    )

                await page.wait_for_timeout(2000)

        # Step 4.5: ウェブサイトカードのヘッドライン / URL を入力
        # 「ウェブサイト」を選択した場合、メディアアップロード後に
        # 「詳細」セクション内のヘッドライン（必須）と URL を埋める
        # ※ 「詳細」セクションはメディアアップロード後に自動展開されている
        if lp_url and media_file_paths:
            logger.info("Filling website card fields (headline / URL)")

            headline_text = ad_name if ad_name else "詳細はこちら"

            # ページ下部にスクロールして FormInput フィールドを表示
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

            # ヘッドライン入力: input.FormInput の最初（空のプレースホルダー）
            headline_filled = False
            try:
                form_inputs = page.locator("input.FormInput")
                count = await form_inputs.count()
                logger.info("Found %d FormInput elements", count)

                if count >= 1:
                    headline_inp = form_inputs.nth(0)
                    await headline_inp.scroll_into_view_if_needed()
                    await headline_inp.click()
                    await headline_inp.fill(headline_text)
                    headline_filled = True
                    logger.info("Headline filled: %s", headline_text)
            except Exception as e:
                logger.warning("Headline fill via FormInput failed: %s", e)

            # URL 入力: input.FormInput の2番目（placeholder="https://"）
            url_filled = False
            try:
                url_inp = page.locator('input[placeholder="https://"]').first
                if await url_inp.is_visible(timeout=3000):
                    await url_inp.click()
                    await url_inp.fill(lp_url)
                    url_filled = True
                    logger.info("URL filled: %s", lp_url)
            except Exception as e:
                logger.warning("URL fill failed: %s", e)

            # フォールバック: FormInput の2番目
            if not url_filled:
                try:
                    form_inputs = page.locator("input.FormInput")
                    if await form_inputs.count() >= 2:
                        url_inp = form_inputs.nth(1)
                        current = await url_inp.input_value()
                        if not current or current == "https://":
                            await url_inp.click()
                            await url_inp.fill(lp_url)
                            url_filled = True
                            logger.info("URL filled via fallback: %s", lp_url)
                except Exception as e:
                    logger.warning("URL fallback fill failed: %s", e)

            if not headline_filled:
                logger.warning("Could not fill headline field")
            if not url_filled:
                logger.warning("Could not fill URL field")

            # フォーカスを外して変更を確定
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(1500)

            # デバッグ用スクリーンショット
            ss_path = str(self.session_dir / "after_card_fields.png")
            await page.screenshot(path=ss_path, full_page=True)
            logger.info("After card fields screenshot: %s", ss_path)

        # デバッグ: ポスト前の状態をスクリーンショット
        ss_path = str(self.session_dir / "before_post.png")
        await page.screenshot(path=ss_path)
        logger.info("Pre-post screenshot saved: %s", ss_path)

        # Step 5: 「ポスト」ボタンをクリック（右上のボタン）
        # スクロールを戻してボタンを表示
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        post_btn = page.locator("button", has_text="ポスト").or_(
            page.locator("button", has_text="Post")
        ).first
        await post_btn.wait_for(timeout=10000)
        await page.wait_for_timeout(1000)

        # ボタンが enabled になるのを待つ
        try:
            await page.wait_for_function(
                """() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.includes('ポスト') || btn.textContent.includes('Post')) {
                            return !btn.disabled;
                        }
                    }
                    return false;
                }""",
                timeout=10000,
            )
        except Exception:
            logger.warning("Post button may still be disabled, attempting click anyway")

        await post_btn.click()
        logger.info("Post button clicked")

        # Step 6: ポスト作成完了を待つ
        try:
            await page.wait_for_url("**/tweets_manager/**", timeout=30000)
            logger.info("Redirected to tweets manager")
        except Exception:
            await page.wait_for_timeout(5000)
            logger.info("Current URL after post: %s", page.url)

        # Step 7: ポスト一覧に遷移してポストIDを取得
        # ※ ポスト作成後、tweets_manager にリダイレクトされることがある。
        #    その場合でも明示的にナビゲーションして最新のデータを取得する。
        tweets_url = (
            f"https://ads.x.com/tweets_manager/{ads_account_id}/tweets"
        )
        logger.info("Navigating to tweets manager: %s", tweets_url)
        await page.goto(tweets_url, wait_until="domcontentloaded", timeout=30000)

        # 最新ポストのIDを抽出（ポーリング付き、最大60秒待機）
        tweet_id = await self._extract_latest_tweet_id(page)

        if tweet_id:
            logger.info("Created post ID: %s", tweet_id)
            return {
                "success": True,
                "tweet_id": tweet_id,
                "message": f"Post created. ID: {tweet_id}",
            }

        # ID取得失敗 — ページリロードしてリトライ（1回だけ）
        logger.warning("First ID extraction failed, reloading page for retry...")
        await page.reload(wait_until="domcontentloaded", timeout=30000)
        tweet_id = await self._extract_latest_tweet_id(page)

        if tweet_id:
            logger.info("Created post ID (after reload): %s", tweet_id)
            return {
                "success": True,
                "tweet_id": tweet_id,
                "message": f"Post created. ID: {tweet_id}",
            }

        ss_path = str(self.session_dir / "post_created_no_id.png")
        await page.screenshot(path=ss_path)
        logger.error(
            "Post was likely created but tweet ID extraction failed. "
            "Screenshot: %s, URL: %s",
            ss_path, page.url,
        )
        return {
            "success": False,
            "tweet_id": None,
            "message": "Post may have been created but ID extraction failed.",
        }

    async def _extract_latest_tweet_id(self, page: Page) -> str | None:
        """ポスト一覧ページから最新ポストのIDを抽出する。

        ポスト一覧のテーブルは非同期でデータを読み込むため、
        テーブル要素の存在だけでなく実際のデータ行が表示されるまでポーリングする。
        """
        import re

        try:
            # テーブル要素が存在するのを待つ（ヘッダー含む）
            await page.wait_for_selector("table", timeout=15000)

            # データ行が読み込まれるまでポーリング（最大60秒）
            for attempt in range(12):
                page_text = await page.inner_text("body")

                # ポストIDは 203... で始まる19-20桁の数字
                ids = re.findall(r"\b(20\d{17,18})\b", page_text)
                if ids:
                    logger.info(
                        "Tweet ID found on attempt %d: %s", attempt + 1, ids[0]
                    )
                    return ids[0]

                logger.info(
                    "No tweet IDs in page yet (attempt %d/12), waiting 5s...",
                    attempt + 1,
                )
                await page.wait_for_timeout(5000)

            # 全リトライ失敗 → デバッグスクリーンショット
            ss_path = str(self.session_dir / "tweet_id_extraction_failed.png")
            await page.screenshot(path=ss_path)
            logger.warning(
                "No tweet IDs found after 12 attempts (60s). Screenshot: %s",
                ss_path,
            )
            return None
        except Exception as e:
            logger.warning("Failed to extract tweet ID: %s", e)
            return None

    async def close(self):
        """ブラウザリソースを解放"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
