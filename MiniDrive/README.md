# MiniDrive

MiniDrive là bài tập Django mô phỏng một dịch vụ lưu trữ file nhỏ. Người dùng có
thể tạo folder, upload file, tìm kiếm, sửa metadata, đánh dấu sao, dùng thùng rác
và tạo link chia sẻ. Project có Django Template, REST API, Bearer token, Celery và
Redis.

## Cài đặt

Chạy từ thư mục gốc repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r MiniDrive/requirements.txt
cd MiniDrive
python manage.py migrate
python manage.py createsuperuser  # không bắt buộc nếu dùng tài khoản seed bên dưới
python manage.py runserver
```

Mở `http://127.0.0.1:8000/`. File upload thật được lưu trong
`MiniDrive/media/uploads/<năm>/<tháng>/`.

Các trang thường dùng:

```text
http://127.0.0.1:8000/          Dashboard của user
http://127.0.0.1:8000/staff/    Dashboard của staff
http://127.0.0.1:8000/admin/    Django Admin
```

Chạy Redis, Celery worker và Celery beat ở hai terminal khác:

```bash
brew services start redis
../.venv/bin/celery -A MiniDrive worker --pool=solo -l info
../.venv/bin/celery -A MiniDrive beat -l info
```

## Dữ liệu và tài khoản test

Tạo dữ liệu mẫu:

```bash
python manage.py seed_drive
```

| Username | Password | Quyền |
|---|---|---|
| `demo_admin` | `DemoAdmin123!` | Superuser |
| `demo_staff` | `DemoStaff123!` | Staff |
| `demo_user1` | `DemoUser123!` | User |
| `demo_user2` | `DemoUser123!` | User |

Các mật khẩu này chỉ dùng để chấm bài hoặc chạy local, không dùng khi deploy thật.
Lệnh `seed_drive` có thể chạy lại nhiều lần. Mỗi lần chạy, lệnh sẽ đặt lại đúng
mật khẩu trong bảng trên và không tạo trùng tài khoản. Dữ liệu mẫu gồm folder
`Documents`, folder con `Reports`, folder `Personal`, ba file và hai label.

Đăng nhập nhanh trên giao diện bằng `demo_user1`. Muốn kiểm tra trang staff thì
dùng `demo_staff`; muốn vào Django Admin thì dùng `demo_admin`.

## Authentication API

Lấy Bearer token:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_user1","password":"DemoUser123!"}'
```

Gửi token trong các request tiếp theo:

```text
Authorization: Bearer <token>
```

Đăng xuất và xóa token hiện tại:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/logout/ \
  -H "Authorization: Bearer <token>"
```

Các nhóm API chính nằm dưới `/api/folders/`, `/api/files/`, `/api/trash/`,
`/api/share-links/`, `/api/activity-logs/` và `/api/staff/`.

Các endpoint chính:

```text
POST         /api/auth/login/
POST         /api/auth/logout/
GET/POST     /api/folders/
GET/PATCH/DELETE /api/folders/<id>/
POST         /api/folders/<id>/restore/
DELETE       /api/folders/<id>/permanent/
GET          /api/files/
POST         /api/files/upload/
GET/PATCH/DELETE /api/files/<id>/
POST         /api/files/<id>/restore/
DELETE       /api/files/<id>/permanent/
POST         /api/files/<id>/star/
POST         /api/files/<id>/unstar/
GET          /api/files/<id>/view/?token=<share-token>
GET          /api/files/<id>/download/
POST         /api/files/<id>/share-links/
GET/POST     /api/share-links/
DELETE       /api/share-links/<id>/
GET          /api/activity-logs/
GET          /api/trash/
GET          /api/trash/files/
GET          /api/trash/folders/
GET          /api/staff/storage-stats/
GET          /api/staff/file-summary/
GET          /api/staff/activity-logs/
GET          /api/staff/reports/
```

Kiểm tra nhanh đăng nhập và một API có yêu cầu xác thực:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_user1","password":"DemoUser123!"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')

curl http://127.0.0.1:8000/api/files/ \
  -H "Authorization: Bearer $TOKEN"
```

## Kiểm tra project

```bash
../.venv/bin/python manage.py check
../.venv/bin/python manage.py makemigrations --check --dry-run
../.venv/bin/python manage.py test drive
```

## Trả lời câu hỏi lý thuyết

### Django

1. **Form validation chạy khi nào?**
   Validation chạy khi gọi `form.is_valid()`. Django kiểm tra field,
   `clean_<field>()`, rồi đến `clean()`.

2. **`clean_<field>()` khác `clean()` như thế nào?**
   `clean_name()` chỉ kiểm tra field `name`. `clean()` dùng khi nhiều field liên
   quan với nhau, ví dụ `parent` phải cùng owner với folder.

3. **Vì sao không nên dùng `fields = "__all__"`?**
   Field mới thêm vào model có thể tự xuất hiện ngoài ý muốn. Khai báo tường minh
   giúp kiểm soát dữ liệu user được phép nhập.

4. **Model `clean()` khác form validation như thế nào?**
   Model `clean()` giữ quy tắc của bản ghi. Form validation kiểm tra dữ liệu từ
   giao diện và có thể gắn lỗi vào từng field.

5. **Custom `save()` dùng để làm gì?**
   Dùng để xử lý trước khi lưu. `FileItem.save()` lấy tên, size, MIME type từ file
   và đồng bộ `deleted_at` với `is_deleted`.

6. **`update()` khác `bulk_update()` như thế nào?**
   `update()` chạy một câu SQL trên QuerySet. `bulk_update()` nhận danh sách object
   đã sửa trong Python rồi cập nhật các field được chọn.

7. **`bulk_update()` có gọi `save()` không?**
   Không, nên custom `save()` và signal liên quan đến `save()` không chạy.

8. **`bulk_create()` có gọi `save()` không?**
   Không. Nó insert nhiều object nhanh hơn nhưng bỏ qua custom `save()`.

9. **Manager khác QuerySet như thế nào?**
   Manager là điểm bắt đầu như `FileItem.objects`. QuerySet là truy vấn có thể nối
   tiếp như `.active().owned_by(user).search("pdf")`.

10. **Khi nào viết method trong QuerySet, khi nào viết trong Manager?**
    Method lọc dữ liệu và cần chain tiếp nên đặt trong QuerySet. Method báo cáo cấp
    model như `storage_summary_by_user()` hợp lý hơn ở Manager.

11. **`values()` khác `values_list()` như thế nào?**
    `values()` trả dictionary. `values_list()` trả tuple; thêm `flat=True` có thể
    lấy một danh sách ID.

12. **`F()` giúp gì khi tăng `download_count`?**
    `F()` tăng trực tiếp trong database, tránh hai request cùng đọc giá trị cũ rồi
    ghi đè lên nhau.

13. **`select_related()` và `prefetch_related()` khác nhau như thế nào?**
    `select_related()` JOIN ForeignKey/OneToOne. `prefetch_related()` chạy truy vấn
    riêng rồi ghép dữ liệu, phù hợp ManyToMany như labels.

### View và Template

14. **`dispatch()` trong class-based view làm gì?**
    Nó nhận request rồi chọn `get()`, `post()`, `patch()` hoặc `delete()` theo HTTP
    method. `FileDownloadAPIView` dùng nó để chặn file chưa `ready`.

15. **Một request đi qua Django view như thế nào?**
    URL resolver tìm route, middleware xử lý request, view kiểm tra quyền và chạy
    nghiệp vụ, sau đó response đi qua middleware về client.

16. **Context trong template đến từ đâu?**
    Context là dictionary do view truyền sang template. `TemplateView` thường thêm
    dữ liệu trong `get_context_data()`.

### Admin

17. **Làm sao để thêm hoặc bớt field trong admin?**
    Dùng `fields` hoặc `fieldsets` cho trang edit và `list_display` cho trang danh
    sách.

18. **Làm sao để readonly một model trong admin?**
    Dùng `readonly_fields`. Nếu model chỉ được đọc thì trả `False` trong các method
    `has_add_permission()`, `has_change_permission()` và `has_delete_permission()`.

19. **Admin action dùng để làm gì?**
    Nó xử lý nhiều bản ghi được chọn cùng lúc, ví dụ soft delete, restore, block
    file hoặc deactivate share link.

### Celery

20. **Background task là gì?**
    Là công việc chạy ngoài request chính để user không phải chờ tác vụ lâu.

21. **Celery dùng để làm gì?**
    Celery đưa công việc vào hàng đợi và cho worker xử lý nền. MiniDrive dùng nó để
    scan file, purge trash, expire link và tính lại dung lượng.

22. **Broker là gì?**
    Broker giữ và chuyển message task từ Django sang worker. Project dùng Redis.

23. **Worker là gì?**
    Worker là process nhận task từ broker và thực thi hàm Celery task.

24. **Enqueue task như thế nào?**
    Gọi `scan_uploaded_file.delay(file_id)` hoặc dùng `apply_async()`.

25. **`delay()` khác `apply_async()` như thế nào?**
    `delay()` là cách gọi ngắn. `apply_async()` hỗ trợ thêm thời điểm chạy, queue
    và các tùy chọn khác.

**Vì sao scan file, gửi email và purge trash nên chạy nền?** Những việc này có thể
chậm hoặc không cần hoàn thành trước khi trả response. Chạy nền giúp request upload
trả kết quả sớm hơn và không bắt user chờ.

**Nếu worker không chạy thì task có được xử lý không?** Không xử lý ngay. Task đã
enqueue sẽ nằm trong broker và chờ đến khi worker hoạt động lại.

### Django REST Framework

26. **Serializer khác Form như thế nào?**
    Form phục vụ HTML. Serializer validate JSON/API và chuyển model thành dữ liệu
    response.

27. **Authentication dùng để làm gì?**
    Nó xác định request đến từ user nào. API đọc Bearer token và gán user vào
    `request.user`.

28. **Permission dùng để làm gì?**
    Nó quyết định user có được thực hiện hành động trên endpoint hoặc object không.

29. **Authentication khác Permission như thế nào?**
    Authentication trả lời “bạn là ai”; permission trả lời “bạn được làm gì”.

30. **Vì sao cần object-level permission?**
    Vì quyền phụ thuộc từng file. Owner hoặc staff được truy cập, guest cần share
    token hợp lệ và đúng loại permission.

### AJAX

31. **AJAX trong bài được dùng ở đâu?**
    Form upload trên Dashboard gọi `POST /api/files/upload/` bằng `fetch()`.

32. **Vì sao upload bằng AJAX thay vì submit form truyền thống?**
    Trang không reload, có thể hiện trạng thái/lỗi ngay và thêm file mới vào danh
    sách sau khi server trả JSON.

33. **CSRF được xử lý như thế nào khi gọi AJAX?**
    Template tạo token bằng `{% csrf_token %}`. JavaScript gửi token trong header
    `X-CSRFToken`.

34. **JavaScript hiển thị lỗi từ server như thế nào?**
    Code đọc JSON, gom message của từng field và ghi vào `upload-message`. Nút
    upload được bật lại trong `finally`.

## Tài liệu thêm

Xem [Sổ tay MiniDrive](docs/SO_TAY_DU_AN.md) để đọc kỹ hơn về model, form,
serializer, permission, QuerySet và Celery task.
