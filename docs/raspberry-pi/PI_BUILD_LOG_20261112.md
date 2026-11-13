# Raspberry Pi 4B 再構築ログ（2026-11-12・Claude Code。G0〜G1 進行中）

**位置づけ：**実機構築の実施記録と手順。設計の草案は Draft PR #357。実行許可・M1受容・本番稼働ではない。Antigravity による設計レビュー（PR #357）は PASS、実機操作は NOT_RUN。

## 1. 現状（2026-11-12 夜）
| 項目 | 状態 |
|---|---|
| 書込対象 | I:（`Cの追加容量`、62.2GB、Windows Disk 2、USB カードリーダー）。書込前に空であることを確認 |
| 元データのバックアップ | O:\RaspberryPi_SD64_Backup_20261112 と C: 側の 2 か所目。各 25 ファイル、SHA-256 一致 |
| 触らないもの | C:（Windows）、H:（SOGH-WORK・Work 所有）、O:（SubDrive）。旧 32GB microSD は初期化せず保管 |
| 媒体の Warning | I:・O: とも「Full Repair Needed」（ファイルシステムの修復印。物理ディスクは Healthy）。I: のカード／リーダーに 11/11 のコントローラーエラー履歴あり → Imager の書込後検証が合否判断 |
| Imager | v2.0.12。Device＝Raspberry Pi 4、OS＝Raspberry Pi OS (64-bit) Desktop。ホスト名 `sogh-pi`、地域 日本／Asia/Tokyo、ユーザー・Wi-Fi 設定済み（秘密値は記録しない）、SSH＝公開鍵認証、Raspberry Pi Connect＝オフ |
| 書込 | 本人が Imager で実行中（2026-11-12 夜、約 50% 時点で記録）。結果は未確認 |
| 操作の限界 | Imager は管理者権限で動作し、Claude の画面操作は遮断される（Windows UIPI）。設定入力と書込は本人の手操作。画面操作＝NOT_RUN |
| SSH 鍵 | 専用の ED25519 鍵 `sogh_pi_ed25519`（秘密鍵は本人の PC のみ。公開鍵だけを Imager に設定）。署名用の `sogh_approver` には触れない |

## 2. 書込完了後の手順（G1 → G2）
1. **G1 完了確認：**Imager が「検証済み（Verified）」を表示するまで待つ。エラーなら停止して内容を記録（カード／リーダーの不調を疑い、別カードを検討）。ここでカードを取り外す。
2. **物理操作（本人）：**旧 32GB を抜いて保管 → 新 64GB を Pi に装着 → Pi 4B 用電源（USB-C 5V/3A）を接続。LAN ケーブルがあれば推奨（Wi-Fi は SSID `Buffalo-A-…`）。初回起動は 2〜3 分（容量拡張・Wi-Fi 接続）。
3. **接続探索（Claude）：**`pi_probe.ps1` で `sogh-pi.local` の応答と 22 番ポートを確認。見つからなければルーターの接続機器一覧（本人）か同一 LAN の ARP で探す。外部公開・ポート開放はしない。
4. **SSH 初回接続：**`ssh -i ~/.ssh/sogh_pi_ed25519 <ユーザー名>@sogh-pi.local`。初回のホスト鍵フィンガープリントを記録し、可能なら Pi の画面（モニター接続時）の値と照合する。ホスト鍵確認の無効化はしない。
5. **G2 の実測（読み取りのみ）：**OS（`/etc/os-release`、`uname -a`）、RAM（`free -h`）、ストレージ（`lsblk`、`df -h`）、温度・電源（`vcgencmd measure_temp`、`get_throttled`）、時刻（`timedatectl`。RTC なし）、ネットワーク（`ip addr`）、カードのエラー（`dmesg` の mmc/I/O）、SSH 設定（パスワード認証が無効か）。結果を PASS/FAIL/NOT_RUN で記録。
6. **初期設定（許可範囲）：**`apt update/upgrade`、時刻同期（systemd-timesyncd）、SD 書込寿命対策（ログの扱い。Antigravity 指摘）、ファイアウォール既定は閉じたまま。
7. **独立 QA：**G2 の実測結果と SSH 設定は、Antigravity に独立確認を依頼（作者分離）。
8. **G3 の準備：**Pi 上に独立した作業領域（Python 仮想環境）、合成イベントのみの状態 API（`127.0.0.1`）。SOGH 本体・正本 DB・実データ・実モデルは扱わない。

## 3. 継続するブロッカー・リスク
- 媒体：I: のカード／リーダーが不安定な可能性（上記）。O: も修復印あり（バックアップは 2 か所）。
- 実機の電源・LAN・モニターは本人側の確認待ち。Pi の RAM（過去記録では 4GB）は未測定。
- G4 以降（表示・常駐）、G5〜（3 台連携・通知・正本）は別の権限・QA ゲート。

## 4. 実績（2026-11-12 20:3x JST 追記）
### G1：書込（本人が Imager で実行）
- 書込後の Windows 側の読取：カードに 2 区画（bootfs 512MB FAT32、Linux 約 6.2GB）。`user-data` に hostname `sogh-pi`、Asia/Tokyo、keyboard jp、`ssh_pwauth: false`、専用 SSH 公開鍵、ユーザー `sogh`。Wi-Fi の秘密値・パスワードは確認・記録していない。Imager の「検証済み」表示は Claude は未観測（本人が書込成功を報告）。**G1：PASS（Pi が起動し、設定どおり動作したことで実証）**。
### G2：SSH 接続と実測（読み取りのみ。Claude が実施）
| 項目 | 結果 |
|---|---|
| 到達 | `sogh-pi.local` が名前解決、22 番ポート開。MAC の先頭 DC-A6-32 は Raspberry Pi の識別子（IPv6 の EUI-64 とも一致）。IP は 192.168.11.25（Wi-Fi wlan0、eth0 は未接続） |
| SSH | 専用鍵で接続 PASS。ホスト鍵 ED25519 の SHA256：`SxivwX1AxLs0DfmSxD1Zg3j1nWUb3VEsVv/2Do0abQI`（初回の accept-new で登録。Pi の画面との照合は NOT_RUN）。パスワード認証は拒否（`Permission denied (publickey)`）＝PASS |
| 本体 | Raspberry Pi 4 Model B Rev 1.2、4 コア、RAM 3789MB、Debian 13 (trixie)、カーネル 6.18.50+rpt-rpi-v8 aarch64 |
| ストレージ | mmcblk0 58GB。/ は 57GB 中 6.1GB 使用、/boot/firmware 505MB。初回起動でファイルシステムを自動拡張（エラーなし）。カードの I/O エラー、`mmc` のエラー：なし（カーネルログ確認。dmesg の全量は sudo なしの範囲） |
| 温度・電源 | 36.5℃、`throttled=0x0`（低電圧・サーマルスロットリングなし） |
| 時刻 | JST、NTP 同期済み（RTC なし＝再起動直後は同期まで時刻が不確か） |
| 待受 | 22（SSH）と 111（rpcbind）が全インターフェースで待受。111 は不要 → 後で無効化を提案（sudo が必要） |
| 権限 | `sudo` はパスワード必須（NOPASSWD ではない）。パスワードは Claude は持たない |
| 状態 | systemd は running、デフォルトは graphical.target（Desktop）。稼働 2 分時点 |
**G2：PASS（自己確認）。** 独立 QA：NOT_RUN（Antigravity への生の接続権限は付与していない。証拠の記録レビューのみ可）。
### 次
- sudo が要る作業（`apt update/upgrade`、rpcbind 停止、SD 書込寿命対策、ログ設定）は、本人がパスワードを入力する形、または別の許可を取って進める。
- G3：Pi 上の独立作業領域に、合成データだけの状態 API（127.0.0.1）。

## 5. 管理者権限の限定付与と初期設定（2026-11-12 夜 追記）
- **限定 sudo：**本人が 1 回だけ `sudo bash ~/sogh_enable_admin.sh` を実行（パスワードは本人が入力。Claude は保持しない）。root 所有の固定ツール `/usr/local/sbin/sogh-admin`（root:root 0755）と、`/etc/sudoers.d/sogh-claude`（visudo 検査済み）で、`sogh` ユーザーは**次の完全一致のコマンドだけ**パスワードなしで実行可：`apt-upgrade`、`rpcbind-off`、`journal-limit`、`sshd-effective`、`kernel-log`、`reboot`、`state-service {start|stop|restart|status|enable|disable}`。それ以外の sudo はパスワード必須（実機で確認：`sudo -n /bin/true` → "a password is required"、`state-service bogus` → 拒否）。ツールは sogh が書き換えられず、権限の拡大には本人の sudo が要る。取消：`sudo rm /etc/sudoers.d/sogh-claude /usr/local/sbin/sogh-admin`。
- 注意（観測）：本人が sudo を使った直後の約 15 分は、パスワードの記憶（global tty 設定）で一般の sudo が通った。`sudo -K` で消去して再確認済み。
- **実施：**`apt-upgrade`（204 件の処理、EXIT=0、再起動不要）、`rpcbind-off`（待受は 22 のみに）、`journal-limit`（journald 50MB／RAM 30MB 上限）。`sshd -T`：`passwordauthentication no`、`pubkeyauthentication yes`、`kbdinteractiveauthentication no`、`permitrootlogin without-password`（root に鍵なし。将来 `no` に絞る提案）。
- **ホスト鍵の照合：**本人が Pi の画面のターミナルで表示した指紋が、Claude が Windows から記録した `SHA256:SxivwX1AxLs0DfmSxD1Zg3j1nWUb3VEsVv/2Do0abQI` と一致（画面照合 PASS）。
- 状態：G1 PASS、G2 PASS（自己確認）。G3 コードは PR #362 として独立QA PASS のうえ master に統合済み（本節 §6 で更新）。

## 6. 更新（2026-11-12 夜・Claude Code）：G3〜G4 の現況
- **G3：**状態 API（`pi/sogh_state/`）は PR #362 で独立QA（A-18）PASS・master 統合済み。Pi 上ではユーザー用の systemd サービスとして稼働（127.0.0.1:8765 のみ、再起動後も自動起動を確認）。
- **G4：**最小表示は PR #368 で独立QA（A-20）PASS・master 統合済み。Pi のモニターに全画面表示、再起動後も自動起動（`~/.config/labwc/autostart`）。本人が目視で確認。
- **SOC 画面 v2：**名称を「SOGH オペレーションセンター（SOC）」に（本人の指定）。日本時間、更新間隔と古い判定の表示、10 分の推移、日本語固定。Draft PR #378（自己テスト 11 件、独立QA A-26 待ち）。Pi には自己テスト済みの版を先に反映。
- **G5 以降：**未着手。G6（他の機器・GitHub との通信）は別の正式許可が必要。

## 7. G5（観測性）の最初の一歩：SD カードへの書込量（2026-11-13）
- SOC 画面に『SDカードへの書込（起動後）』を追加（`/proc/diskstats` の mmcblk0 の書込セクタ数×512。読めなければ『不明』で、数値を推測しない）。追加の書込を起こさない（読み取りだけ）。
- 実測（Pi、稼働 約 14.3 時間）：**約 149 MiB**（≒ 10 MiB／時間、約 250 MiB／日）。journald を 50MB に制限済み。この速さなら、一般的な 64GB の SD カードの書込寿命に対して、1 年で約 90GB 程度で、当面の問題にならない見込み（長期の傾向は継続して見る）。
- 欠測の扱い：デバイスやファイルが読めないとき、壊れた値のときは `None`（画面は『不明』）。試験で固定。
