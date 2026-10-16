"""GUI-controlled DEMO execution port with strict readback guards.

No orders are performed during imports, tests, construction or inspection.
Only a user-initiated "fill both" may reach submit_once. Every broker account
must be reverified as DEMO immediately before ONE click. The command is NEVER
retried on timeout/uncertainty. Position reading is required both before
and after the click; missing/multiple/unknown IDs fail closed.
"""
from __future__ import annotations

import hashlib
import re
import time
from decimal import Decimal, InvalidOperation

from .auto_entry import DemoAccount, Position
from .windows import AutomationError, WindowInfo, WindowController


class DemoUiBrokerPort:
    def __init__(self, automation, log, *, draw_internal=False):
        self.automation=automation
        self.log=log
        self.draw_internal=draw_internal
        # A position ticket is assigned its role only after the matching
        # new position has been confirmed. Never infer role from the
        # same broker window's possibly shared title binding.
        # Ticket values can overlap across two separate brokers.
        self._ticket_role: dict[tuple[str, str], str] = {}
        self._account_binding: dict[tuple[str, str], DemoAccount] = {}
        self._expected_symbol: str | None = None
        # Local performance telemetry only. No accounts, quantities or
        # trading data are logged; this never changes order-click behavior.
        self.submit_phase_timings: dict[str, dict[str, float]] = {}

    def prove_terminal_rejection(self, platform: str, role: str,
                                 attempt_key: str, account_id: str,
                                 symbol: str):
        # No authenticated, correlated broker order status/history is
        # exposed by the current GUI-only adapter. An empty Positions grid
        # or timeout is NOT a definitive rejection. Fail closed.
        return None

    def remember_verified_position_role(
        self, platform: str, role: str, position: Position
    ) -> None:
        """Local bookkeeping after a separately verified read-only fill."""
        if (role not in ("internal","external")
            or position.platform != platform or not position.ticket):
            raise AutomationError("成交持倉與場別不一致，拒絕修改止盈止損。")
        expected=self._account_binding.get((platform,role))
        if expected is None or expected.account_id != position.account_id:
            raise AutomationError("持倉帳戶與已核對 Demo 帳戶不一致。")
        key=(platform,position.ticket)
        current=self._ticket_role.get(key)
        if current is not None and current!=role:
            raise AutomationError("同一持倉在兩邊場別的對應關係矛盾。")
        self._ticket_role[key]=role

    def set_expected_symbol(self, symbol: str) -> None:
        self._expected_symbol=str(symbol or "").strip().upper()

    def _verify_instrument(
        self, platform: str, role: str, win, *, _controls=None
    ) -> None:
        expected=self._expected_symbol
        if not expected:
            raise AutomationError("沒有可信的本次商品代碼，禁止送單。")
        # Instrument identity MUST match the actual order pane now open,
        # not merely a chart seen earlier or the spreadsheet label.
        if "MT5" in platform.upper():
            title=str(win.title or "").upper()
            accepted=(
                ("XAUUSD",) if expected in ("GOLD","XAUUSD")
                else ("XAGUSD",) if expected in ("SILVER","XAGUSD")
                else (expected,)
            )
            if not any(
                re.search(r"(?<![A-Z])"+re.escape(s)+r"(?![A-Z])",title)
                for s in accepted
            ):
                raise AutomationError(
                    f"MT5 訂單商品與試算表 {expected} 未核對成功。"
                )
            return
        from pywinauto import Desktop
        descriptions={
            "GOLD":"Gold vs US Dollar",
            "XAUUSD":"Gold vs US Dollar",
            "XAGUSD":"Silver vs US Dollar",
            "SILVER":"Silver vs US Dollar",
            "EURUSD":"Euro vs US Dollar",
        }
        wanted=descriptions.get(expected)
        if not wanted:
            raise AutomationError(
                f"cTrader 尚未驗證 {expected} 商品描述欄位，拒絕送單。"
            )
        if _controls is None:
            info=Desktop(backend="uia").window(handle=win.handle)
            controls=info.descendants(control_type="Text")
        else:
            controls=_controls
        matches=[
            item for item in controls
            if str(item.element_info.control_type)=="Text"
            and item.is_visible() and
            str(item.element_info.automation_id).endswith(
                "SymbolQuickInfoTemplates__TextBlock_Description_AId"
            ) and str(item.window_text()).strip()==wanted
            and item.rectangle().left>=1400
            and 145<=item.rectangle().top<=280
        ]
        if len(matches)!=1:
            raise AutomationError(
                f"cTrader 目前開單商品不是唯一的 {wanted}，禁止送單。"
            )

    def _bind_verified_account(
        self, platform: str, role: str, account: DemoAccount
    ) -> DemoAccount:
        key=(platform,role)
        previous=self._account_binding.get(key)
        if previous is not None and previous!=account:
            raise AutomationError(
                f"{role} {platform} 交易帳戶在執行期間被切換，"
                "已停止送單；請重新檢查帳號和持倉。"
            )
        self._account_binding[key]=account
        return account

    def _bound(self, platform, role):
        profile=self.automation.config["platforms"][platform]
        pattern=profile["window_title"][role]
        if (platform in ("cTrader", "GooeyTrade")
                and isinstance(self.automation.windows, WindowController)):
            # Real entrypoints share the same canonical calibrated main
            # terminal finder as fill and post-entry work; fake adapters
            # below retain compatibility with existing offline fixtures.
            return profile,self.automation.windows.find_calibrated_main(
                pattern,profile.get("points",{}).get("lot_input",{}),
                platform=platform,
            )
        window=self.automation.windows.find(pattern)
        if "MT5" not in platform.upper() and isinstance(window, WindowInfo):
            # A cTrader popup and the REAL trading window can have the
            # same title. EnumWindows returns the popup first while it is
            # foremost; re-reading the popup will NEVER reveal an account.
            # The user's existing lot-input calibration uniquely identifies
            # the full-size main window without an expensive UIA rescan.
            point=profile.get("points",{}).get("lot_input",{})
            width=int(point.get("window_width",0))
            height=int(point.get("window_height",0))
            if width>0 and height>0 and (
                abs(window.width-width)>2 or abs(window.height-height)>2
            ):
                candidates=self.automation.windows.find_all(pattern)
                matches=[
                    candidate for candidate in candidates
                    if isinstance(candidate,WindowInfo)
                    and abs(candidate.width-width)<=2
                    and abs(candidate.height-height)<=2
                ]
                if len(matches)!=1:
                    raise AutomationError(
                        "cTrader 標題相符但校準尺寸無唯一主視窗"
                        f"（符合 {len(matches)} 個），不操作。"
                    )
                window=matches[0]
                self.log(
                    "cTrader 偵測到同名對話視窗；已選回唯一"
                    "符合校準尺寸的主交易視窗。"
                )
        return profile,window

    @staticmethod
    def _decimal(raw, *, empty_ok=False):
        text=str(raw or "").strip().replace("\u00a0","").replace(" ","")
        if text in ("","—","–","-","N/A"):
            if empty_ok:return None
            raise AutomationError("Demo 持倉數值空白，不可推測。")
        if text.count(",") and text.count("."):
            text=text.replace(",","")
        elif text.count(",")==1 and "." not in text:
            first,last=text.split(",")
            text=text.replace(",", "." if len(last)!=3 else "")
        try:
            result=Decimal(text)
        except (ValueError,InvalidOperation) as exc:
            raise AutomationError(f"Demo 持倉數值不可辨識：{raw!r}") from exc
        if not result.is_finite():
            raise AutomationError("Demo 持倉數值不是有限數。")
        return result

    @classmethod
    def _ctrader_quantity_lots(cls, raw) -> Decimal:
        """Read cTrader's quantity as LOTS, not as a raw numeric UI label.

        cTrader native Positions UIA currently renders e.g. "0.74 Lots".
        The known trailing 'Lot'/'Lots' token is a display unit, not part
        of the amount. Don't change the price/SL/TP numeric parser.
        """
        value = str(raw or "").strip().replace("\u00a0", " ")
        match = re.fullmatch(
            r"(?P<number>[+-]?[\d., ]+)\s+Lots?",
            value, re.IGNORECASE,
        )
        if match is not None:
            value = match.group("number").strip()
        # Treat a clearly formatted European grouped amount 1.000,25
        # as 1000.25, not 1.00025. Unknown mixed-separator formats must
        # stop rather than silently change a trading volume.
        cleaned = value.replace(" ", "")
        if "." in cleaned and "," in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                if not re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+,\d+", cleaned):
                    raise AutomationError(
                        f"cTrader Lots 手數格式不明：{raw!r}"
                    )
                value = cleaned.replace(".", "").replace(",", ".")
            elif not re.fullmatch(
                r"[+-]?\d{1,3}(?:,\d{3})+\.\d+", cleaned
            ):
                raise AutomationError(
                    f"cTrader Lots 手數格式不明：{raw!r}"
                )
        number = cls._decimal(value)
        if number <= 0:
            raise AutomationError(
                f"cTrader 持倉 Lots 手數非正數，無法確認：{raw!r}"
            )
        return number

    @staticmethod
    def _side(raw):
        text=str(raw).strip().casefold()
        if text in ("buy","long","買入","多"):return "BUY"
        if text in ("sell","short","賣出","空"):return "SELL"
        raise AutomationError(f"持倉方向無法可靠辨識：{raw!r}")

    def inspect_account(
        self, platform: str, role: str, *, _controls=None, _window=None
    ) -> DemoAccount:
        if _window is None:
            profile,window=self._bound(platform,role)
        else:
            window=_window
        title=str(window.title or "")
        if "MT5" in platform.upper():
            m=re.search(r"\b(\d{5,})\s*-\s*([^\s-]+(?:-[^\s-]+)*-Demo)\b",
                        title,re.IGNORECASE)
            if not m:
                raise AutomationError(
                    f"{role} MT5 視窗未確認 Demo 帳號和伺服器，禁止送單。"
                )
            return self._bind_verified_account(
                platform,role,
                DemoAccount(platform,m.group(1),m.group(2),True,True)
            )
        from pywinauto import Desktop
        try:
            # A transient UIA tree may omit the cTrader account number
            # during a window transition. Retry ONLY when its count is zero.
            # Duplicate IDs, changed identities and non-DEMO still fail closed.
            for attempt in range(1 if _controls is not None else 3):
                elements=(
                    _controls if _controls is not None
                    else Desktop(backend="uia").window(
                        handle=window.handle
                    ).descendants()
                )
                number_nodes=[
                    element for element in elements
                    if (str(element.element_info.automation_id)==
                        "CTraderAccountNumberTextBlock_AId"
                        and element.is_visible())
                ]
                if number_nodes or _controls is not None or attempt==2:
                    break
                self.log(
                    "cTrader identity UIA temporarily missing; "
                    f"read-only retry {attempt+1}/2."
                )
                time.sleep(0.12)
            def unique(aid):
                found=[e for e in elements if e.is_visible() and
                       str(e.element_info.automation_id)==aid]
                if len(found)!=1:
                    raise AutomationError(
                        f"cTrader 缺少唯一的 {aid} 帳戶控制項。"
                    )
                return str(found[0].window_text()).strip()
            number=unique("CTraderAccountNumberTextBlock_AId")
            kind=unique("CTraderAccountTypeTextBlock_AId")
            broker=[e for e in elements if e.is_visible() and
                    "BrokerNameShort" in str(e.element_info.automation_id)]
            if (not number.isdigit() or len(number)<5 or
                kind.casefold()!="demo" or len(broker)!=1 or
                not broker[0].window_text().strip()):
                raise AutomationError("cTrader 沒有可確認的 Demo 帳戶識別。")
            return self._bind_verified_account(
                platform,role,
                DemoAccount(
                    platform,number,broker[0].window_text().strip(),True,True
                )
            )
        except AutomationError:
            raise
        except Exception as exc:
            raise AutomationError(f"cTrader Demo 帳戶唯讀驗證失敗：{exc}") from exc

    def _ctrader_grid(self, platform, role):
        from pywinauto import Desktop
        _,win=self._bound(platform,role)
        root=Desktop(backend="uia").window(handle=win.handle)
        grids=[g for g in root.descendants(control_type="DataGrid") if
               g.is_visible() and
               str(g.element_info.automation_id)=="PositionListDataGrid_AId"]
        if len(grids)!=1:
            raise AutomationError("cTrader Positions 清單不唯一或未顯示。")
        return grids[0]

    def _ctrader_positions(self, platform, role, account):
        grid=self._ctrader_grid(platform,role)
        rows=grid.descendants(control_type="DataItem")
        # A hidden zero-size DataItem can be a cTrader empty-grid placeholder.
        # Never treat a virtualized or unreadable real row as empty.
        ghosts=bool(rows)
        for row in rows:
            try:
                rect=row.rectangle()
                if (row.is_visible() or rect.right>rect.left
                        or rect.bottom>rect.top):
                    ghosts=False
                    break
            except Exception:
                ghosts=False
                break
        if ghosts:
            try:
                count=int(grid.iface_grid.CurrentRowCount)
                time.sleep(0.1)
                count2=int(grid.iface_grid.CurrentRowCount)
                any_text=any(
                    str(node.window_text()).strip()
                    for row in rows
                    for node in row.descendants(control_type="Text")
                )
            except Exception as exc:
                raise AutomationError(
                    "cTrader placeholder cannot be verified; position unknown."
                ) from exc
            if count==count2==0 and not any_text:
                return ()
            raise AutomationError(
                "cTrader grid count conflicts with placeholder nodes; "
                "cannot prove an empty position list."
            )
        if not rows:return ()
        headers={}
        for h in grid.descendants(control_type="HeaderItem"):
            name=str(h.window_text()).strip().casefold()
            if name in ("symbol","quantity","direction","entry price",
                        "sl","tp","created (utc+0)"):
                if name in headers:raise AutomationError(
                    f"cTrader 持倉表欄名重複：{name}"
                )
                headers[name]=h.rectangle()
        required=("symbol","quantity","direction","entry price",
                  "sl","tp","created (utc+0)")
        if any(k not in headers for k in required):
            raise AutomationError("cTrader 持倉清單必要欄名缺失，拒絕辨識成交。")
        found=[]
        for row in rows:
            rr=row.rectangle()
            children=row.descendants()
            values={}
            for name in required:
                h=headers[name]
                texts=[]
                for node in children:
                    try:
                        rect=node.rectangle()
                        center=(rect.left+rect.right)//2
                        if (str(node.element_info.control_type)=="Text"
                            and h.left<=center<=h.right
                            and rr.top<=rect.top and rect.bottom<=rr.bottom):
                            val=str(node.window_text()).strip()
                            if val:texts.append(val)
                    except Exception:
                        continue
                if len(texts)!=1:
                    raise AutomationError(
                        f"cTrader {name} 欄沒有唯一原生讀值（{len(texts)}）。"
                    )
                values[name]=texts[0]
            created=values["created (utc+0)"]
            if not created or len(created)<6:
                raise AutomationError("cTrader 持倉建立時間無法確認。")
            ticket=hashlib.sha256(
                (account.account_id+"|"+values["symbol"]+"|"+
                 values["direction"]+"|"+created).encode("utf-8")
            ).hexdigest()[:20]
            found.append(Position(
                ticket,account.account_id,platform,values["symbol"],
                self._side(values["direction"]),
                self._ctrader_quantity_lots(values["quantity"]),
                self._decimal(values["entry price"]),
                self._decimal(values["sl"],empty_ok=True),
                self._decimal(values["tp"],empty_ok=True),
            ))
        tickets=[p.ticket for p in found]
        if len(tickets)!=len(set(tickets)):
            raise AutomationError("cTrader 唯一持倉識別碼重複，拒絕進場。")
        return tuple(found)

    def _mt5_positions(self, platform, role, account):
        from pywinauto import Desktop
        _,win=self._bound(platform,role)
        window=Desktop(backend="win32").window(handle=win.handle)
        views=[w for w in window.descendants()
               if w.class_name()=="SysListView32" and w.control_id()==10328
               and w.is_visible()]
        if len(views)!=1:
            raise AutomationError("MT5 Trade 分頁持倉表未顯示或不唯一。")
        view=views[0]
        if len(view.columns())<9:
            raise AutomationError("MT5 持倉表欄位不足，拒絕讀取。")
        positions=[]
        blank_rows=0
        for i in range(view.item_count()):
            cols=[str(view.get_item(i,j).text() or "").strip() for j in range(9)]
            if not any(cols):
                blank_rows+=1
                continue
            ticket=cols[1]
            if not ticket.isdigit() or len(ticket)<5:
                raise AutomationError(
                    "MT5 持倉表含非訂單列，無法確定是否切在 Trade 分頁。"
                )
            positions.append(Position(
                ticket,account.account_id,platform,cols[0],
                # MT5 Win32 ListView has an undisplayed subitem #2:
                # ticket=1, time=3, type=4, volume=5, entry=6,
                # SL=7, TP=8. Do not assume visual column index==subitem.
                self._side(cols[4]),
                self._decimal(cols[5]),
                self._decimal(cols[6]),
                self._decimal(cols[7],empty_ok=True),
                self._decimal(cols[8],empty_ok=True),
            ))
        # On some MT5 terminals, virtual/owner-drawn Win32 ListView
        # items report blank text even when the on-screen Trade tab has
        # a position. Multiple unreadable items are UNKNOWN, not 0 orders.
        if blank_rows>1 and not positions:
            raise AutomationError(
                "MT5 Trade 清單回傳多筆空白虛擬列，無法證明空倉；"
                "禁止將持倉數誤判為 0，請確認交易分頁與持倉。"
            )
        if len(set(x.ticket for x in positions))!=len(positions):
            raise AutomationError("MT5 持倉表有重複訂單編號。")
        return tuple(positions)

    def snapshot_positions(self, platform, role) -> tuple[Position,...]:
        account=self.inspect_account(platform,role)
        if platform=="MT5":
            # MT5's owner-drawn Trade ListView often returns blank UIA rows
            # although a real open trade is visible. Query ONLY the native
            # terminal's read-only account/position API; it is independently
            # Demo/account-verified and contains NO order_send operation.
            from .mt5_native_readonly import snapshot_mt5_demo
            return snapshot_mt5_demo(account)
        if "MT5" in platform.upper():
            # Other differently installed MT5 terminals are not silently
            # connected to the main ICMarkets terminal by the native API.
            return self._mt5_positions(platform,role,account)
        return self._ctrader_positions(platform,role,account)

    @staticmethod
    def _mt5_owned_order_dialog(main_handle: int, dialog_handle: int) -> bool:
        """Require the actual native MT5 modal, owned by the bound terminal."""
        try:
            import win32gui
            import win32process
            return (
                win32gui.GetClassName(dialog_handle) == "#32770"
                and win32gui.GetWindow(dialog_handle, 4) == main_handle
                and win32process.GetWindowThreadProcessId(dialog_handle)[1]
                    == win32process.GetWindowThreadProcessId(main_handle)[1]
            )
        except Exception:
            return False

    def _form_window(self, platform,role, *, allow_absent=False):
        profile,main=self._bound(platform,role)
        if "MT5" not in platform.upper():
            return profile,main
        point=profile.get("points",{}).get("lot_input")
        if not point:
            raise AutomationError("MT5 未校準手數欄位。")
        width=int(point.get("window_width",0))
        height=int(point.get("window_height",0))
        if width<=0 or height<=0:
            raise AutomationError("MT5 訂單視窗的校準尺寸無效。")
        # The saved order title may contain a broker-specific suffix (+)
        # or an older translated description. Never fall back to the
        # terminal's MAIN HWND just because that outdated regex fails.
        # A true MT5 order dialog is an owned native #32770 modal.
        matches=[]
        wrong_sizes=[]
        owned_order_dialogs=[]
        for candidate in self.automation.windows.list_windows():
            if candidate.handle==main.handle:
                continue
            if not re.match(
                r"^(?:Order|訂單|订单)\s*[:：]\s*",
                str(candidate.title or ""),re.IGNORECASE
            ):
                continue
            if not self._mt5_owned_order_dialog(
                main.handle,candidate.handle
            ):
                continue
            owned_order_dialogs.append(candidate)
            try:
                self._verify_instrument(platform,role,candidate)
            except AutomationError:
                continue
            if (abs(candidate.width-width)>2 or
                    abs(candidate.height-height)>2):
                wrong_sizes.append((candidate.width,candidate.height))
                continue
            matches.append(candidate)
        # A missing dialog is an expected condition during the initial
        # prefill check. An existing wrong-symbol/wrong-size/ambiguous
        # dialog is NOT missing: fail closed instead of opening another.
        if allow_absent and not owned_order_dialogs:
            return profile,None
        if len(matches)!=1:
            extra=(
                f"；找到的視窗尺寸為 {wrong_sizes}，校準為 {width}x{height}"
                if wrong_sizes else ""
            )
            raise AutomationError(
                f"MT5 沒有找到唯一、同帳戶主視窗持有且商品吻合的"
                f"訂單對話框（符合 {len(matches)} 個）{extra}。"
                "不使用主視窗代替，未送出訂單。"
            )
        return profile,matches[0]

    def validate_auto_entry_capabilities(
        self, internal_platform: str, external_platform: str,
        internal_direction: str, external_direction: str,
        *, sync_sl_tp: bool, draw_tv: bool
    ) -> None:
        """All configurable post-entry prerequisites checked before Send.

        This validation is read-only; it does not click any broker action.
        Requiring the MODIFY calibration in advance avoids opening the
        internal leg only to discover the intended SL/TP workflow cannot run.
        """
        for platform,role,direction,needs_modify in (
            (internal_platform,"internal",internal_direction,
             "MT5" in internal_platform.upper()),
            (external_platform,"external",external_direction,sync_sl_tp),
        ):
            profile=self.automation.config["platforms"][platform]
            points=profile.get("points",{})
            required=[
                "lot_input","sl_input","tp_input",
                ("order_submit_buy" if direction=="BUY"
                 else "order_submit_sell")
                if "MT5" in platform.upper() else "order_submit_button",
            ]
            if needs_modify:
                required.extend((
                    "position_order_row","position_sl_input",
                    "position_tp_input","position_modify_confirm",
                ))
            missing=[]
            malformed=[]
            for key in required:
                point=points.get(key)
                if not point:
                    missing.append(key)
                    continue
                if not isinstance(point,dict) or not all(
                    isinstance(point.get(k),(int,float)) and
                    point[k]>=0
                    for k in ("x_px","y_px","window_width","window_height")
                ) or not point["window_width"] or not point["window_height"]:
                    malformed.append(key)
            if missing or malformed:
                raise AutomationError(
                    f"{role} {platform} 自動進場預檢未通過："
                    f"缺校準 {', '.join(missing) or '無'}；"
                    f"座標不完整 {', '.join(malformed) or '無'}。"
                    "請先完成校準後重新執行，未送出任何訂單。"
                )
        if draw_tv:
            if not sync_sl_tp:
                raise AutomationError("先同步 SL/TP 才能自動畫 TV。")
            tv=self.automation.config.get("platforms",{}).get("TradingView")
            if not tv or not tv.get("points"):
                raise AutomationError(
                    "選了自動畫 TV，但 TradingView 尚未校準，"
                    "本次不允許自動送單。"
                )
            try:
                self.automation.windows.find(
                    tv["window_title"]["internal"]
                )
            except Exception as exc:
                raise AutomationError(
                    f"無法在進場前確認 TradingView 視窗：{exc}"
                ) from exc

    def verify_order_form(
        self, platform,role,direction,lot, *,
        _controls=None, _window=None
    ) -> None:
        # Ordinary preflight still reads independent fresh broker evidence.
        # Only the final cTrader pre-click path reuses its ONE new UIA tree.
        if _controls is None:
            self.inspect_account(platform,role)
        else:
            self.inspect_account(
                platform,role,_controls=_controls,_window=_window
            )
        profile,win=(
            self._form_window(platform,role) if _window is None
            else (self.automation.config["platforms"][platform],_window)
        )
        self._verify_instrument(platform,role,win,_controls=_controls)
        points=profile.get("points",{})
        try:
            kwargs=({"_controls":_controls} if _controls is not None else {})
            snap=self.automation.windows.read_fill_snapshot(
                win,points,ctrader="MT5" not in platform.upper(),**kwargs
            )
            observed=self.automation._normalize_numeric_input(
                snap["values"]["lot_input"],lot
            )
        except Exception as exc:
            raise AutomationError(f"{role} {platform} 送單前表單讀回失敗：{exc}") from exc
        if observed!=lot:
            raise AutomationError(
                f"{role} {platform} 手數被改動：預期 {lot}、實際 {observed}。"
            )
        for key in ("sl_input","tp_input"):
            number=self.automation._normalize_numeric_input(
                snap["values"][key]
            )
            if ("MT5" in platform.upper() and number<=0) or (
                "MT5" not in platform.upper() and number==0
            ):
                # cTrader's Stop-loss points may legitimately be signed
                # (e.g. -527); MT5 SL/TP are absolute positive prices.
                raise AutomationError(
                    f"{role} {key} 沒有有效數值，禁止送單。"
                )
        if "MT5" not in platform.upper():
            if snap["direction"]!=direction:
                raise AutomationError("cTrader 買賣方向和試算表不一致。")
            if not all(snap["checks"].get(k) for k in
                       ("sl_checkbox","tp_checkbox")):
                raise AutomationError("cTrader SL／TP 有未勾選項目。")

    def submit_once(self,platform,role,direction,lot,key):
        # Fresh verify_order_form already calls inspect_account internally.
        # Do not enumerate the same cTrader account controls a second time;
        # keep the independent FULL fresh pre-click form readback unchanged.
        timestamps={"start":time.perf_counter()}
        controls=None
        if "MT5" not in platform.upper():
            # One fresh post-focus UIA inventory serves ALL independent
            # semantic guards: Demo account, instrument, form and order
            # button. Never reuse an earlier preflight inventory.
            profile,win=self._form_window(platform,role)
            self.automation.emergency.guard()
            self.automation.windows.focus(win)
            from pywinauto import Desktop
            controls=Desktop(backend="uia").window(
                handle=win.handle
            ).descendants()
            timestamps["uia_inventory_returned"]=time.perf_counter()
            self.automation.emergency.guard()
            self.verify_order_form(
                platform,role,direction,lot,
                _controls=controls,_window=win,
            )
        else:
            self.verify_order_form(platform,role,direction,lot)
            profile,win=self._form_window(platform,role)
        timestamps["form_verified"]=time.perf_counter()
        points=profile["points"]
        click_point=None
        if "MT5" in platform.upper():
            point_key=("order_submit_buy" if direction=="BUY"
                       else "order_submit_sell")
            point=points.get(point_key)
            if not point:
                raise AutomationError("MT5 沒有人工確認過的市價送單校準位置。")
            # Recheck actual red Sell / blue Buy geometry, regardless
            # of platform locale, before trusting a saved mouse position.
            from PIL import ImageGrab
            from .mt5_visual_scan import detect_order_dialog_regions
            from .calibration_scan import (
                _mt5_client_geometry,_resolve_mt5_capture_origin
            )
            image=ImageGrab.grab(window=win.handle)
            size,origin=_mt5_client_geometry(win.handle)
            rect=(win.left,win.top,win.left+win.width,win.top+win.height)
            source=_resolve_mt5_capture_origin(image.size,rect,size,origin)
            if source is None:
                raise AutomationError("MT5 截圖座標未對齊，拒絕送單。")
            regions=detect_order_dialog_regions(image)
            bounds=regions.get(point_key)
            if not bounds:
                raise AutomationError("MT5 找不到唯一紅／藍送單鍵，拒絕送單。")
            x,y=self.automation.windows.screen_point(win,point)
            xa,ya,xb,yb=bounds
            if not (xa+source[0]<=x<=xb+source[0] and
                    ya+source[1]<=y<=yb+source[1]):
                raise AutomationError("MT5 校準位置不在當前送單鍵內，拒絕送單。")
        else:
            point=points.get("order_submit_button")
            if not point:
                raise AutomationError("cTrader 尚未人工校準真正的 Place order。")
            # Native button from the SAME fresh checked inventory; type,
            # ID, parent ancestry and calibrated location remain mandatory.
            buttons=[b for b in controls
                if str(b.element_info.control_type)=="Button"
                and b.is_visible() and b.is_enabled() and
                str(b.element_info.automation_id)==
                "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId"
            ]
            if len(buttons)!=1:
                raise AutomationError("cTrader 找不到唯一 Place order 按鈕。")
            button=buttons[0]
            # Check the native UIA hierarchy to prevent confusing the
            # real order submission with a direction/new-order control.
            parent=button
            ancestors=[]
            try:
                for _ in range(2):
                    parent=parent.parent()
                    ancestors.append(str(parent.element_info.automation_id))
            except Exception as exc:
                raise AutomationError(
                    f"cTrader 送單鍵父層無法驗證：{exc}"
                ) from exc
            if ancestors!=["AspPlaceOrderButton_AId","PropertySectionView_AId"]:
                raise AutomationError("cTrader 送單鍵不在已確認的下單面板內。")
            rect=button.rectangle()
            x,y=self.automation.windows.screen_point(win,point)
            if rect.left<=x<=rect.right and rect.top<=y<=rect.bottom:
                click_point=point
            else:
                # SL/TP fields may expand vertically after calibration.
                # Allow ONLY a small vertical movement of this exact
                # uniquely identified native button, never a distant
                # or horizontally displaced unrelated control.
                vertical_gap=max(rect.top-y,y-rect.bottom,0)
                if not (rect.left<=x<=rect.right and vertical_gap<=200):
                    raise AutomationError(
                        "cTrader 送單鍵已偏離校準區域（距離"
                        f" {vertical_gap}px），為安全起見未送單；"
                        "請重新校準真正的 Place order。"
                    )
                center_x=(rect.left+rect.right)//2
                center_y=(rect.top+rect.bottom)//2
                click_point=self.automation.windows.relative_point(
                    win,center_x,center_y
                )
                self.log(
                    "cTrader SL/TP 面板改變了送單鍵位置；"
                    f"已從校準點 ({x},{y}) 對準唯一原生 Place order"
                    f" 中心 ({center_x},{center_y})，不改寫校準。"
                )
        self.automation.emergency.guard()
        # The ONLY broker order submission click in this module.
        # Never retry it in case of timeout or uncertain acknowledgement.
        timestamps["click_started"]=time.perf_counter()
        self.automation.windows.click(win,click_point or point)
        timestamps["click_returned"]=time.perf_counter()
        self.submit_phase_timings[role]=timestamps

    def confirm_new_position(self,platform,role,baseline,direction,volume,account_id):
        previous={p.ticket for p in baseline}
        deadline=time.monotonic()+12
        while True:
            self.automation.emergency.guard()
            observed=self.snapshot_positions(platform,role)
            newer=[p for p in observed if p.ticket not in previous]
            if len(newer)==1 and len(observed)==len(baseline)+1:
                self.remember_verified_position_role(
                    platform,role,newer[0]
                )
                return newer[0]
            if len(newer)>1 or len(observed)<len(baseline):
                raise AutomationError("持倉變化不只一筆，無法確認唯一成交。")
            if time.monotonic()>=deadline:
                raise AutomationError(
                    "Demo 送單後 12 秒內未確認唯一新持倉，禁止再次送單。"
                )
            time.sleep(0.3)

    def verify_internal_protection(self,pos,sl_points,tp_points):
        after=self.snapshot_positions(pos.platform,"internal")
        selected=[p for p in after if p.ticket==pos.ticket]
        if len(selected)!=1:
            raise AutomationError("場內持倉在核對 SL／TP 時不存在或不唯一。")
        row=selected[0]
        if row.sl is None or row.tp is None or row.sl<=0 or row.tp<=0:
            raise AutomationError("場內持倉沒有有效 SL／TP，停止場外進場。")
        if (row.direction=="BUY" and
            not (row.sl<row.entry_price<row.tp)) or (
            row.direction=="SELL" and
            not (row.tp<row.entry_price<row.sl)):
            raise AutomationError("場內持倉 SL／TP 方向不合理。")

    def set_position_sl_tp(self,pos,sl,tp):
        role=self._ticket_role.get((pos.platform,pos.ticket))
        if role not in ("internal","external"):
            raise AutomationError("缺少經過成交確認的持倉場別，拒絕修改。")
        positions=self.snapshot_positions(pos.platform,role)
        if len(positions)!=1 or positions[0].ticket!=pos.ticket:
            raise AutomationError("修改前無法唯一確認要修改的 Demo 持倉。")
        profile,win=self._bound(pos.platform,role)
        points=profile.get("points",{})
        required=("position_order_row","position_sl_input",
                  "position_tp_input","position_modify_confirm")
        missing=[k for k in required if k not in points]
        if missing:
            raise AutomationError(
                f"{pos.platform} 修改持倉前缺少校準：{', '.join(missing)}"
            )
        self.automation.windows.double_click(
            win,points["position_order_row"]
        )
        try:
            modify=self.automation.windows.wait_for_active_window_change(
                win,timeout=3.0
            )
        except AutomationError:
            modify=self.automation.windows.wait_for_window_matching_point_size(
                points["position_sl_input"],timeout=3.0,
                exclude_handles={win.handle},
            )
        for key,value in (
            ("position_sl_input",sl),("position_tp_input",tp)
        ):
            self.automation.emergency.guard()
            text=str(value)
            self.automation.windows.click_and_type(
                modify,points[key],text
            )
            readback=self.automation.windows.read_edit_value(
                modify,points[key]
            )
            actual=self.automation._normalize_numeric_input(readback,value)
            if actual!=value:
                raise AutomationError(
                    f"{key} 修改框讀回 {readback} 與目標 {value} 不符，"
                    "拒絕按確認。"
                )
        self.automation.emergency.guard()
        self.automation.windows.click(modify,points["position_modify_confirm"])

    def verify_position_sl_tp(self,pos,sl,tp):
        role=self._ticket_role.get((pos.platform,pos.ticket))
        if role not in ("internal","external"):
            raise AutomationError("缺少經過成交確認的持倉場別，拒絕讀回。")
        deadline=time.monotonic()+8
        while True:
            self.automation.emergency.guard()
            positions=self.snapshot_positions(pos.platform,role)
            matching=[p for p in positions if p.ticket==pos.ticket]
            if len(matching)!=1:
                raise AutomationError("SL／TP 修改後無法唯一確認原持倉。")
            current=matching[0]
            if current.sl==sl and current.tp==tp:
                return
            if time.monotonic()>deadline:
                raise AutomationError(
                    "SL／TP 修改送出後，無法從持倉清單確認新價格。"
                )
            time.sleep(0.25)

    def draw_tradingview(self,instruction,internal_platform,entry,draw_internal):
        self.automation.draw_tradingview(
            instruction,internal_platform=internal_platform,
            entry_price_override=entry,draw_internal=draw_internal
        )