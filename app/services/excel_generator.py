"""X Ads Editor 形式の Excel ファイル生成"""
from __future__ import annotations

import json
from io import BytesIO
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.models import Project, SubmissionBatch, SubmissionCampaign

# X Ads Editor のキャンペーンシート 102カラム（日本語ヘッダー）
EXCEL_COLUMNS = [
    "キャンペーンID",                          # 0
    "お支払い方法ID",                          # 1
    "キャンペーン名",                          # 2
    "キャンペーン開始日",                       # 3
    "キャンペーン終了日",                       # 4
    "広告キャンペーン予算の最適化",               # 5
    "キャンペーンステータス",                    # 6
    "配信",                                    # 7
    "キャンペーン総予算",                       # 8
    "広告キャンペーンの日別予算",                # 9
    "広告代理店クレジットライン発注番号",          # 10
    "キャンペーンのフリークエンシー上限",          # 11
    "キャンペーンのフリークエンシー上限が適用される期間",  # 12
    "広告グループID",                          # 13
    "キャンペーンの目的",                       # 14
    "広告グループ名",                          # 15
    "広告グループの開始時刻",                    # 16
    "広告グループの終了時刻",                    # 17
    "広告グループの状態",                       # 18
    "広告グループの総予算",                      # 19
    "広告グループの日別予算",                    # 20
    "配信",                                    # 21
    "広告グループのフリークエンシー上限",          # 22
    "広告グループのフリークエンシー上限が適用される期間",  # 23
    "目標",                                    # 24
    "広告グループの配信先",                      # 25
    "プロモ商品タイプ",                         # 26
    "ウェブサイトコンバージョンタグID",            # 27
    "お支払い方法",                             # 28
    "広告主ドメイン",                           # 29
    "入札戦略",                                # 30
    "入札額",                                  # 31
    "情報開示のタイプ",                         # 32
    "情報開示のテキスト",                       # 33
    "IABカテゴリー",                            # 34
    "アプリ",                                  # 35
    "Amplifyプログラム",                        # 36
    "性別",                                    # 37
    "年齢",                                    # 38
    "場所",                                    # 39
    "フォロワーターゲティング",                  # 40
    "フォロワーターゲティングの類似ターゲティング",  # 41
    "プラットフォーム",                         # 42
    "ユーザーのOSバージョン",                    # 43
    "ユーザーの端末",                           # 44
    "Wi-Fiのみ",                               # 45
    "言語",                                    # 46
    "ユーザーの興味関心",                       # 47
    "携帯電話会社",                             # 48
    "端末アクティベーション期間",                # 49
    "完全一致キーワード",                       # 50
    "除外する完全一致キーワード",                # 51
    "部分一致キーワード",                       # 52
    "順不同キーワード",                         # 53
    "除外する順不同キーワード",                  # 54
    "フレーズキーワード",                       # 55
    "除外するフレーズキーワード",                # 56
    "テイラードオーディエンスリスト",             # 57
    "除外するテイラードオーディエンスリスト",      # 58
    "テイラードオーディエンスの類似オーディエンス",  # 59
    "テイラードオーディエンス (モバイルアプリから)",  # 60
    "除外するテイラードオーディエンス (モバイルアプリから)",  # 61
    "テイラードオーディエンス (モバイルアプリから) の類似オーディエンス",  # 62
    "テイラードオーディエンスのウェブサイト訪問者",  # 63
    "除外するテイラードオーディエンスのウェブサイト訪問者",  # 64
    "テイラードオーディエンスのウェブサイト訪問者の類似オーディエンス",  # 65
    "インストールされているアプリのカテゴリー",    # 66
    "インストールされているアプリのカテゴリーの類似カテゴリー",  # 67
    "TAP - 除外するアプリ",                     # 68
    "予約済み",                                # 69
    "TAP - パブリッシャーアプリのカテゴリー",      # 70
    "TV番組",                                  # 71
    "イベントターゲティングID",                  # 72
    "キャンペーンのリターゲティング",             # 73
    "オーガニックなツイートのリターゲティング",     # 74
    "エンゲージメントタイプをリターゲティング",     # 75
    "ツイートID",                              # 76
    "予約投稿ツイートID",                       # 77
    "プロモアカウントID",                       # 78
    "予約済み",                                # 79
    "TAPメディアクリエイティブアプリID",           # 80
    "TAPメディアクリエイティブランディングURL",     # 81
    "メディアクリエイティブID",                  # 82
    "予約済み",                                # 83
    "予約済み",                                # 84
    "Google Campaign Manager tags",            # 85
    "予約済み (2)",                             # 86
    "予約済み（3）",                            # 87
    "フレキシブルオーディエンス",                 # 88
    "柔軟なオーディエンスを除外",                # 89
    "柔軟なオーディエンスの類似オーディエンス",     # 90
    "Amplifyプログラムから自動プロモーション",     # 91
    "予約済み",                                # 92
    "予約済み",                                # 93
    "類似オーディエンスの拡張設定",              # 94
    "会話",                                    # 95
    "ターゲティングするパブリッシャーアカウント",   # 96
    "除外したパブリッシャーアカウント",            # 97
    "除外したIABカテゴリー",                     # 98
    "標準カテゴリー",                           # 99
    "Amplifyプレロールプレミアムカテゴリー",       # 100
    "予約済み",                                # 101
]

# X Ads Editor のObjective値マッピング
OBJECTIVE_MAP = {
    "WEBSITE_CLICKS": "WEBSITE_CLICKS",
    "WEBSITE_CONVERSIONS": "WEBSITE_CONVERSIONS",
    "APP_INSTALLS": "APP_INSTALLS",
    "ENGAGEMENTS": "ENGAGEMENTS",
    "REACH": "REACH",
    "VIDEO_VIEWS": "VIDEO_VIEWS",
    "FOLLOWERS": "FOLLOWERS",
}

# 入札戦略マッピング
BID_STRATEGY_MAP = {
    "AUTO": "AUTO",
    "TARGET": "TARGET",
    "MAX": "MAX",
}


def _json_to_semicolon(value: Optional[str]) -> str:
    """JSON配列をセミコロン区切りの文字列に変換"""
    if not value:
        return ""
    try:
        items = json.loads(value)
        if isinstance(items, list):
            return ";".join(str(i) for i in items)
        return str(items)
    except (json.JSONDecodeError, TypeError):
        return str(value)


def _format_budget(value: Optional[int]) -> str:
    """予算値をフォーマット（カンマ区切り）"""
    if value is None:
        return ""
    return f"{value:,}"


class ExcelGenerator:
    """X Ads Editor 形式の Excel ファイル生成"""

    def generate(
        self,
        batch: SubmissionBatch,
        project: Optional[Project] = None,
    ) -> BytesIO:
        """SubmissionBatch から Excel ワークブックを生成"""
        wb = Workbook()

        # メインシート: Campaigns
        ws = wb.active
        ws.title = "Campaigns"
        self._build_campaigns_sheet(ws, batch.campaigns, project)

        # 参照シート
        ws2 = wb.create_sheet("お支払い方法ID (編集不可)")
        self._build_payment_sheet(ws2, batch.campaigns, project)

        ws3 = wb.create_sheet("コンバージョンタグID (編集不可)")
        self._build_conversion_tags_sheet(ws3, batch.campaigns)

        ws4 = wb.create_sheet("テイラードオーディエンスID (編集不可)")
        self._build_audiences_sheet(ws4)

        ws5 = wb.create_sheet("メディアクリエイティブID (編集不可)")
        self._build_media_sheet(ws5)

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def _build_campaigns_sheet(
        self,
        ws,
        campaigns: list[SubmissionCampaign],
        project: Optional[Project],
    ):
        """キャンペーンシートを構築"""
        # ヘッダー行
        header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
        header_font = Font(bold=True, size=10)

        for col_idx, header in enumerate(EXCEL_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="left", wrap_text=True)

        # データ行
        for row_idx, campaign in enumerate(campaigns, 2):
            row_data = self._campaign_to_row(campaign, project)
            for col_idx, value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=value)

        # 列幅を調整
        for col_idx in range(1, len(EXCEL_COLUMNS) + 1):
            letter = get_column_letter(col_idx)
            max_len = len(str(EXCEL_COLUMNS[col_idx - 1]))
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=col_idx, max_col=col_idx):
                for cell in row:
                    if cell.value:
                        max_len = max(max_len, min(len(str(cell.value)), 40))
            ws.column_dimensions[letter].width = max_len + 2

        # ヘッダー行を固定
        ws.freeze_panes = "A2"

    def _campaign_to_row(
        self,
        c: SubmissionCampaign,
        project: Optional[Project],
    ) -> list:
        """SubmissionCampaign を 102要素のリストに変換"""
        row = [""] * len(EXCEL_COLUMNS)

        # Campaign-level (0-12)
        row[0] = c.api_campaign_id or ""                      # キャンペーンID
        row[1] = c.funding_instrument_id                      # お支払い方法ID
        row[2] = c.campaign_name                              # キャンペーン名
        row[3] = c.start_time or ""                           # キャンペーン開始日
        row[4] = c.end_time or ""                             # キャンペーン終了日
        row[5] = c.campaign_budget_optimization or ""         # 予算の最適化
        row[6] = "ACTIVE"                                     # キャンペーンステータス
        row[7] = "STANDARD"                                   # 配信
        row[8] = _format_budget(c.campaign_total_budget)      # キャンペーン総予算
        row[9] = _format_budget(c.campaign_daily_budget)      # 日別予算

        # Ad Group-level (13-36)
        row[13] = c.api_line_item_id or ""                    # 広告グループID
        row[14] = c.campaign_objective                        # キャンペーンの目的
        row[15] = c.line_item_name or c.campaign_name         # 広告グループ名
        row[16] = c.start_time or ""                          # 開始時刻
        row[17] = c.end_time or ""                            # 終了時刻
        row[18] = "ACTIVE"                                    # 広告グループの状態
        row[21] = "STANDARD"                                  # 配信
        row[25] = _json_to_semicolon(c.placements)            # 広告グループの配信先
        row[26] = "PROMOTED_TWEETS"                           # プロモ商品タイプ
        row[27] = c.conversion_tag_id or ""                   # ウェブサイトコンバージョンタグID
        row[28] = "CREDIT_CARD"                               # お支払い方法
        row[30] = c.bid_strategy                              # 入札戦略
        row[31] = _format_budget(c.bid_amount) if c.bid_amount else ""  # 入札額

        # Targeting (37-75)
        row[37] = c.target_gender or ""                       # 性別
        row[38] = _json_to_semicolon(c.target_age_ranges)     # 年齢
        row[39] = _json_to_semicolon(c.target_locations)      # 場所
        row[42] = _json_to_semicolon(c.target_platforms)      # プラットフォーム
        row[46] = _json_to_semicolon(c.target_languages)      # 言語

        # Audiences
        if c.target_audiences:
            row[57] = _json_to_semicolon(c.target_audiences)  # テイラードオーディエンスリスト

        # 類似オーディエンス拡張
        if c.audience_expansion:
            row[94] = c.audience_expansion                    # 類似オーディエンスの拡張設定

        # Tweet (76-82)
        if c.tweet_ids:
            tweet_ids = _json_to_semicolon(c.tweet_ids)
            row[76] = tweet_ids                               # ツイートID

        return row

    def _build_payment_sheet(
        self,
        ws,
        campaigns: list[SubmissionCampaign],
        project: Optional[Project],
    ):
        """お支払い方法ID シート"""
        headers = ["お支払い方法ID", "名前", "お支払い方法の状態", "開始日", "お支払い方法のクレジット額 (JPY)"]
        for col_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=col_idx, value=h).font = Font(bold=True)

        # ユニークなfunding_instrument_idを列挙
        fi_ids = set()
        for c in campaigns:
            if c.funding_instrument_id:
                fi_ids.add(c.funding_instrument_id)

        for row_idx, fi_id in enumerate(fi_ids, 2):
            ws.cell(row=row_idx, column=1, value=fi_id)
            ws.cell(row=row_idx, column=3, value="ACTIVE")

    def _build_conversion_tags_sheet(self, ws, campaigns: list[SubmissionCampaign]):
        """コンバージョンタグID シート"""
        headers = ["コンバージョンタグID", "名前"]
        for col_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=col_idx, value=h).font = Font(bold=True)

        tag_ids = set()
        for c in campaigns:
            if c.conversion_tag_id:
                tag_ids.add(c.conversion_tag_id)

        for row_idx, tag_id in enumerate(tag_ids, 2):
            ws.cell(row=row_idx, column=1, value=tag_id)

    def _build_audiences_sheet(self, ws):
        """テイラードオーディエンスID シート"""
        headers = ["テイラードオーディエンスID", "名前", "タイプ", "共有可能"]
        for col_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=col_idx, value=h).font = Font(bold=True)

    def _build_media_sheet(self, ws):
        """メディアクリエイティブID シート"""
        headers = ["メディアクリエイティブID", "メディアタイプ", "アップロード日"]
        for col_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=col_idx, value=h).font = Font(bold=True)
