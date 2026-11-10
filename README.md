# ICT QuantLab — Browser-only edition

ICT QuantLab là workspace nghiên cứu ICT cá nhân, chạy hoàn toàn trong trình duyệt bằng HTML, CSS và JavaScript thuần. Frontend được host trên GitHub Pages và kết nối trực tiếp tới cTrader Open API qua Secure WebSocket JSON. **Không có login nội bộ, FastAPI, Docker, database server hay Cloudflare Worker.**

> Đây là công cụ phân tích nghiên cứu, không đặt lệnh giao dịch. Các thuật toán ICT phải được hiểu là định nghĩa cơ học/proxy có thể kiểm tra, không phải cách diễn giải duy nhất của ICT. Forecast baseline mang tính thống kê mô tả cho đến khi được đánh giá out-of-sample.

## 1. Cấu trúc

```text
index.html
assets/
  styles.css             Dark Quant Terminal UI
  app.js                 UI, browser storage, orchestration
  ctrader-client.js      cTrader JSON WebSocket transport + M1 cache
  research-engine.js     Browser-side ICT/statistics/forecast calculations
.github/workflows/
  deploy-pages.yml       Static validation and GitHub Pages deployment
.nojekyll
```

## 2. Deploy lên GitHub Pages

1. Giải nén source và đưa **toàn bộ nội dung bên trong ZIP** vào root repository. `index.html`, `.nojekyll`, `assets/` và `.github/` phải nằm ngay ở root.
2. Xóa các file/thư mục backend cũ khỏi repository nếu bạn đã upload phiên bản trước, đặc biệt `apps/api/`, `Dockerfile`, `docker-compose.yml` và các workflow deploy backend.
3. Mở **Settings → Pages → Build and deployment**, chọn **GitHub Actions**.
4. Push lên nhánh `main`. Workflow sẽ kiểm tra cú pháp JavaScript, script references và DOM ID trước khi publish. Không cần build Node/npm, không cần Render URL hay GitHub Actions secrets.
5. Website ở dạng `https://GITHUB_USERNAME.github.io/REPOSITORY_NAME/`.

## 3. Kết nối cTrader thủ công

Trong **Data Center → cTrader Open API** nhập:

- **Client ID**: ID ứng dụng Open API đã đăng ký tại cTrader.
- **Client Secret**: Secret tương ứng của ứng dụng.
- **Access Token**: access token đã được cấp quyền cho ứng dụng/tài khoản qua quy trình OAuth cTrader (có thể lấy từ công cụ OAuth/Playground phù hợp). Ứng dụng QuantLab hiện không tự mở luồng OAuth; người dùng dán token thủ công như trong form.
- **Account ID**: tùy chọn; để trống sẽ chọn tài khoản đầu tiên mà token trả về.
- **Environment**: Auto thử Demo rồi Live; hoặc chọn cố định Demo/Live.

Nhấn **Lưu & kết nối**. Client thực hiện `ProtoOAApplicationAuthReq` (2100), lấy account list bằng `ProtoOAGetAccountListByAccessTokenReq` (2149), authorize tài khoản bằng `ProtoOAAccountAuthReq` (2102), lấy danh sách symbol (2114), sau đó yêu cầu historical trendbars M1 (2137). Kết nối dùng JSON qua `wss://demo.ctraderapi.com:5036` hoặc `wss://live.ctraderapi.com:5036`.

Access Token cTrader có thời hạn mặc định khoảng 30 ngày. Khi token hết hạn, lấy/cấp token mới và dán lại vào form. Bản browser-only này chưa tự động refresh OAuth token; đây là lựa chọn có chủ đích để không cần backend/client secret exchange.

Tài liệu chính thức: [Account authentication](https://help.ctrader.com/open-api/account-authentication/), [JSON messages](https://help.ctrader.com/open-api/sending-receiving-json/), [Symbol and trendbar data](https://help.ctrader.com/open-api/symbol-data/).

## 4. Lưu trữ và bảo mật

- Client ID, Client Secret, Access Token, Account ID và môi trường được lưu trong `localStorage` của browser để giữ lại sau reload. Dữ liệu này **không được mã hóa**. Bất kỳ script độc hại/XSS hoặc extension có quyền đọc trang đều có thể truy cập. Chỉ sử dụng trên thiết bị cá nhân, không dùng máy công cộng, không chia sẻ profile trình duyệt và không commit credentials vào GitHub.
- OHLC M1 và coverage cache chỉ nằm trong RAM. Reload/đóng tab làm mất cache; tải lại sẽ gọi cTrader. Mở rộng khoảng thời gian trong cùng phiên chỉ tải các khoảng chưa được cache.
- Research notes, session profile và forecast audit records lưu trong `localStorage`; có thể bị xóa khi người dùng clear site data. Nên export/backup dữ liệu nghiên cứu cần giữ.
- Nếu định chia sẻ website cho nhiều người, **không dùng kiến trúc này**: chuyển Client Secret và token sang backend/Worker, mỗi người dùng OAuth riêng và lưu secret phía server.

## 5. Các module trong UI

### Phase 1 — Core Statistics

1. Gap Statistics — NDOG/NWOG và tiến độ fill 25/50/75/100%.
2. Liquidity Statistics — Asia High/Low, PDH/PDL, sweep/breakout/reclaim.
3. Session Statistics — Asia, London, NY AM/PM và mức độ coverage.
4. Time Statistics — thời điểm daily high/low hình thành và phân phối theo giờ.
5. Market Structure — confirmed pivots, BOS/MSS, MFE/MAE và R-multiples theo horizon trong engine.
6. Daily & Weekly — hướng, range, extreme timing.
7. Liquidity → MSS — phản ứng MSS có điều kiện sau sweep; mẫu thiếu horizon bị loại.

FVG Fill Statistics không thuộc Phase 1; FVG formation/mitigation nằm ở Advanced ICT.

### Advanced ICT và Forecast — mức triển khai hiện tại

Advanced JS engine hiện tính FVG candidate, EQH/EQL candidate và ADR context. OB/Breaker, Premium/Discount, PO3/AMD/Judas, Silver Bullet, CBDR/IPDA, CISD, Three Drives, Quarterly Shift và đầy đủ confluence rules vẫn là các nhóm mở rộng cần được port/đặc tả và kiểm định riêng; UI không nên được hiểu là tất cả đã có thuật toán hoàn chỉnh. SMT cần dữ liệu M1 trùng thời gian của hai symbol.

Forecast hiện là **historical-analogue baseline** với ba scenario độc quyền và quantile price range, cần tối thiểu 30 analogues. Nó chưa phải mô hình GARCH/HMM/XGBoost/LSTM đã huấn luyện. Live mode trong bản hiện tại làm mới latest M1 theo chu kỳ polling; chưa phải push live trendbar subscription. Brier/accuracy chỉ có ý nghĩa khi outcome tương lai đã được tải đủ horizon.

## 6. Quy ước dữ liệu

- Timestamp được giữ UTC trong cache và hiển thị New York Time (`America/New_York`) để DST tự động đổi.
- Trendbar cTrader lưu low và delta; giá được chuyển đổi từ relative values bằng hệ số 100000, làm tròn theo symbol digits. Nến bất khả thi được gắn `suspect_ohlc` và bị loại khỏi tính toán. Đối chiếu chart broker trước khi dùng dữ liệu cho nghiên cứu nghiêm túc.
- M5/M15/M30/H1/H4/D1 được tổng hợp từ M1; nến thiếu thành phần không được coi là nến hoàn chỉnh.
- Kết quả phụ thuộc broker, symbol trading hours, định nghĩa event và chất lượng dữ liệu. Không sử dụng kết quả như khuyến nghị đầu tư.

## 7. Kiểm tra local

Không cần cài dependencies. Với Node.js 20 trở lên:

```bash
node --check assets/ctrader-client.js
node --check assets/research-engine.js
node --check assets/app.js
node tests/ctrader-smoke.cjs
node tests/research-smoke.cjs
```

Có thể mở `index.html` để xem UI, nhưng nhiều trình duyệt chặn WebSocket hoặc một số chức năng khi chạy từ `file://`. Dùng GitHub Pages (HTTPS) để kiểm tra kết nối thực tế. Việc kiểm tra syntax không thay thế kiểm thử bằng tài khoản cTrader hợp lệ.
