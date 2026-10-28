# Định vị trong phòng bằng RSSI

Dự án định vị người/vật trong nhà (indoor localization) dựa trên cường độ tín hiệu WiFi (RSSI). Một số thiết bị cố định đóng vai trò **anchor** đo RSSI, hệ thống đổi RSSI thành khoảng cách rồi dùng **trilateration** để ước tính vị trí của **Target** (thiết bị cần định vị, ví dụ iPhone) trên bản đồ phòng 2D theo thời gian thực.

Dự án gồm 2 file, không cần cài thêm thư viện nào (chỉ dùng thư viện chuẩn của Python):

| File | Vai trò |
|---|---|
| `server.py` | Máy chủ HTTP: nhận mẫu RSSI, lưu lịch sử và log CSV, đọc RSSI WiFi của chính laptop, phục vụ giao diện web |
| `index.html` | Giao diện web: lọc tín hiệu, hiệu chỉnh, tính vị trí và vẽ bản đồ |

## Cách hoạt động

```
Anchor 1 ─┐
Anchor 2 ─┼─ HTTP /rssi ─► server.py ─► /data ─► index.html (trình duyệt)
Anchor 3 ─┘                │                      ├─ lọc RSSI
                           └─► log.csv            ├─ RSSI → khoảng cách
                                                  ├─ trilateration
                                                  └─ vẽ bản đồ
```

1. Mỗi anchor gửi RSSI (dBm) về server qua HTTP.
2. Trình duyệt lấy dữ liệu mới từ `/data` mỗi 250 ms.
3. RSSI được lọc, đổi thành khoảng cách, rồi tính ra vị trí Target.

### 1. Mô hình suy hao đường truyền

```
d = 10 ^ ((A - RSSI) / (10 · n))
```

- `A`: RSSI đo được ở khoảng cách 1 m (mặc định -45 dBm)
- `n`: hệ số suy hao môi trường (mặc định 2.5; không gian trống ≈ 2, trong nhà nhiều vật cản thường 2.5–4)

### 2. Bộ lọc RSSI ("khóa khi đứng yên")

- **Trung vị** 3–5 mẫu gần nhất để loại giá trị nhảy đột biến (cửa sổ lớn hơn nếu thiết bị gửi nhanh ≥ 3 mẫu/giây).
- **Đứng yên**: trung bình cộng dồn, càng nhiều mẫu càng chính xác, tới mức tối thiểu do thanh *Độ mượt* quyết định.
- **Di chuyển**: nếu 2 mẫu liên tiếp lệch quá ngưỡng (5–6 dBm), bỏ giá trị cũ, bám ngay mức mới rồi cộng dồn lại.

Kết quả: lúc đang di chuyển có thể lệch, đứng yên vài giây sẽ hội tụ về giá trị chính xác nhất.

### 3. Tính vị trí

- **≥ 3 anchor**: nghiệm tuyến tính (lấy anchor gần nhất làm mốc), sau đó tinh chỉnh bằng **Gauss-Newton** với trọng số `1/d²` (anchor gần được tin hơn vì sai số RSSI tăng theo khoảng cách). Kết quả bị kẹp trong phạm vi phòng. Nếu 3 anchor thẳng hàng thì không tính được.
- **2 anchor**: ra 2 giao điểm có thể, hiển thị cả hai (điểm chính + điểm mờ). Cần anchor thứ 3 để chọn.
- **1 anchor**: chỉ biết khoảng cách, chưa biết hướng.

Anchor được coi là mất tín hiệu nếu không có dữ liệu mới trong 5 giây và sẽ bị loại khỏi tính toán.

## Yêu cầu

- Python 3.8+
- Các thiết bị cùng một mạng WiFi (khuyến nghị dùng hotspot điện thoại)
- Chế độ anchor-laptop cần: Windows (`netsh`), macOS (`system_profiler`) hoặc Linux (`iw`)

## Cách chạy

### Bước 1: Khởi động server (trên laptop chính)

```bash
python server.py
```

Server in ra các địa chỉ cần dùng:

```
Mo trinh duyet:  http://localhost:8000
Dien thoai gui toi: http://<IP>:8000/rssi?id=anchor1&rssi=-55
iPhone nhap tay: http://<IP>:8000/send
Laptop khac gui: python server.py --send http://<IP>:8000 --id anchor2
```

Mở `http://localhost:8000` để xem giao diện.

### Bước 2: Thêm anchor (chọn một hoặc kết hợp nhiều cách)

**a) Laptop chạy server cũng là anchor**

```bash
python server.py --anchor anchor1
```

Laptop tự đọc RSSI WiFi của mình mỗi 0.5 giây.

**b) Laptop khác làm anchor (chỉ gửi RSSI)**

```bash
python server.py --send http://<IP>:8000 --id anchor2
```

**c) Điện thoại nhập tay**

Mở `http://<IP>:8000/send` trên điện thoại, nhập tên thiết bị và RSSI (ví dụ đọc từ AirPort Utility), bấm **Gửi**. Có thể bật *Tự động gửi lại mỗi giây* và dùng nút -1/+1 để chỉnh giá trị.

**d) Thiết bị bất kỳ gọi HTTP** (ví dụ Phím tắt iPhone, script, ESP32...)

```
GET http://<IP>:8000/rssi?id=anchor3&rssi=-52
```

Chấp nhận `-52`, `-52.5`, `-52 dBm`; số dương sẽ tự đổi thành âm; giá trị phải nằm trong khoảng -110 đến 0.

### Tùy chọn dòng lệnh

| Tham số | Ý nghĩa |
|---|---|
| `--anchor ID` | Laptop này cũng là anchor với tên `ID` |
| `--send URL` | Chỉ gửi RSSI tới server ở máy khác (bắt buộc kèm `--id`) |
| `--id ID` | Tên anchor khi dùng `--send` |
| `--interval GIÂY` | Chu kỳ đo (mặc định 0.5) |

## Sử dụng giao diện

1. **Phòng và bộ lọc**: nhập chiều rộng/dài phòng (m) và chỉnh *Độ mượt*.
2. **Đặt vị trí anchor**: với mỗi anchor, nhập tọa độ `x`, `y` (m) đúng với vị trí thật. Gốc tọa độ là góc dưới trái của phòng. Anchor mới có vị trí mặc định xếp theo kích thước phòng.
3. **Hiệu chỉnh A và n** (nên làm cho từng anchor để có độ chính xác tốt):
   - Đứng yên đúng khoảng cách đã biết (ví dụ 1 m) khoảng 10 giây, nhập khoảng cách thật rồi bấm **Ghi mẫu**.
   - Ghi 2–4 điểm ở các khoảng cách khác nhau (1 m, 2 m, 3 m...). Hệ thống hồi quy bình phương tối thiểu để tự tính `A` và `n`.
   - Với 1 điểm: giữ nguyên `n`, chỉ tính lại `A`.
4. Quan sát **bản đồ**: vòng tròn là khoảng cách đo từ mỗi anchor, chấm đỏ là Target, đường đứt nét nối Target tới từng anchor kèm khoảng cách, đường mờ là vệt di chuyển gần đây.

Cấu hình (kích thước phòng, độ mượt, vị trí, A, n của từng anchor) được lưu trong `localStorage` của trình duyệt. Bấm **Xóa cấu hình đã lưu** để đặt lại.

## API của server

| Endpoint | Mô tả |
|---|---|
| `GET /` | Giao diện chính (`index.html`) |
| `GET /send` | Trang nhập RSSI tay cho điện thoại |
| `GET /rssi?id=<tên>&rssi=<dBm>` | Gửi 1 mẫu RSSI |
| `GET /data?since=<timestamp>` | Lấy các mẫu mới hơn `since` (JSON `{now, rows}`) |

## Dữ liệu và log

- Mọi mẫu được ghi nối tiếp vào `log.csv` (cột `time`, `id`, `rssi`) cùng thư mục với `server.py`.
- Server giữ tối đa 2000 mẫu gần nhất trong bộ nhớ.

## Lưu ý và hạn chế

- RSSI rất nhiễu và phụ thuộc môi trường (vật cản, phản xạ, hướng ăng-ten, cơ thể người), nên sai số vị trí thường ở mức vài chục cm đến hơn 1 m. Hiệu chỉnh `A`, `n` theo từng phòng và từng anchor sẽ cải thiện đáng kể.
- Nên đặt anchor phân tán, không thẳng hàng, bao quanh khu vực cần định vị.
- Trên Windows cũ không có dòng `Rssi`, giá trị được ước lượng từ `Signal %` (dBm ≈ % / 2 - 100), kém chính xác hơn.
- Server lắng nghe trên `0.0.0.0` và không có xác thực, chỉ nên chạy trong mạng cục bộ tin cậy.
- Kết quả chỉ là 2D (x, y), chưa tính độ cao.
