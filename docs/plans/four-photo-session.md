# Luồng tự chụp và ghép bốn ảnh

Nguồn yêu cầu: [plan.md](../../plan.md). Làm trên backend hiện tại và repo Vue nguồn `.local/photobooth-frontend`. Đợt này dùng một khung có sẵn gồm bốn ô và một màn hình. Các phần quản lý mẫu, kéo/zoom, xuất chính thức, Drive, in, màn hình khách và xử lý USB thuộc đợt khác. Giữ nguyên các chế độ chụp hiện có.

## Task 1 — Thiết lập thời gian

- [ ] Kiểm tra cấu hình trong `src/photobooth/services/config/groups/actions.py` và giao diện quản trị hiện có. Tận dụng `countdown_capture`, `countdown_capture_second_following` và `approve_autoconfirm_timeout`. Chế độ bốn ảnh chỉ hiện một giá trị đếm ngược, dùng cho lượt đầu, các lượt tiếp theo và lượt chụp bù. Dùng thêm một giá trị riêng cho thời gian xem lại, tính bằng giây.
- [ ] Cho người vận hành chỉnh cả hai trước khi bắt đầu. Dùng giới hạn hợp lệ từ schema hiện có hoặc bổ sung giới hạn cho chế độ mới nếu còn thiếu. Chốt hai giá trị khi bắt đầu để thay đổi cấu hình không làm lệch phiên đang chạy.
- [ ] Kiểm tra cấu hình với countdown 2 giây và xem lại 5 giây. Hai giá trị phải đọc lại đúng và không ảnh hưởng preset khác; dữ liệu không hợp lệ phải bị từ chối.

## Task 2 — Chụp, duyệt và tự ghép

- [ ] Dùng lại pipeline collage trong `services/processor/collage.py`, các chuyển trạng thái trong `services/processor/machine/processingmachine.py` và màn hình `MediaItemApprovalViewer.vue`. Tạo hoặc cấu hình riêng preset có đúng bốn ô ảnh camera, theo thứ tự chụp, tiết kiệm thay đổi backend khi cấu hình hiện có đáp ứng được.
- [ ] Từ một lần bấm, mỗi lượt chạy đếm ngược → chụp → hiện ảnh → xem lại. Đồng hồ xem lại chỉ bắt đầu khi ảnh đã hiện. Hết giờ hoặc bấm Giữ xác nhận ảnh. Bấm Loại xóa file thuộc phiên hiện tại và chụp bù bằng một lượt đếm ngược đầy đủ. Xử lý tranh chấp hết giờ và bấm nút sao cho mỗi ảnh chỉ nhận một quyết định.
- [ ] Đủ bốn ảnh được giữ, mở bản ghép nháp và kết thúc việc chụp. Tắt xóa/tô/thay nền và loại ảnh demo khỏi các ô. Dùng lại quy tắc tạm dừng/tiếp tục và kết thúc phiên đã ghi trong plan.md. Nếu lỗi camera hoặc không nhận được ảnh, giữ nguyên số ảnh đã chấp nhận và cho người vận hành thấy lỗi.
- [ ] Viết test tập trung cho các hành vi mới ở backend hoặc frontend tương ứng. Kiểm tra tự giữ, giữ ngay, loại và xóa file đúng phạm vi, chụp bù, thao tác sát thời điểm hết giờ, lỗi camera, và dừng ở đúng bốn ảnh. Kiểm tra thứ tự ô và nền thật bằng bốn ảnh thử có dấu nhận biết riêng.

## Task 3 — Kiểm thử và bàn giao

- [ ] Chạy các test liên quan và kiểm tra frontend ở repo nguồn. Dùng camera giả lập trong runtime riêng để thử trên UI một màn hình: chọn hai thời gian khác nhau, bấm bắt đầu một lần, thử đủ ba cách duyệt, quan sát tổng lượt chụp, rồi kiểm tra đúng bốn ảnh trong bản ghép.
- [ ] Ghi phiên bản, vị trí các thay đổi ở hai repo, lệnh chạy, kết quả từng tình huống, và checklist tự thử với D5300. Ghi rõ nếu còn thiếu kiểm tra trình duyệt hoặc phần cứng. Để người dùng tự bấm chụp với D5300.

Phiên thực thi thực hiện tuần tự và báo kết quả từng task. Giữ tài liệu, ảnh và runtime cũ; không sửa trực tiếp frontend bundle, không đổi lockfile nếu không cần, không push/merge, không dừng dịch vụ USB. Phiên điều phối chỉ viết kế hoạch và giao việc.
