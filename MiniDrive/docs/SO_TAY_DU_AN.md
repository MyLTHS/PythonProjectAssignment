# Sổ tay học dự án MiniDrive

Tài liệu này giúp bạn đọc MiniDrive theo đúng thứ tự, hiểu phần nào đang chạy thật,
phần nào mới là nền móng, và biết nên làm gì tiếp theo. Nội dung được đối chiếu với
mã nguồn và 5 test hiện có của dự án.

## 1. MiniDrive đang giải quyết bài toán gì?

MiniDrive mô phỏng một dịch vụ lưu trữ file giống phiên bản nhỏ của Google Drive.
Người dùng dự kiến có thể:

- quản lý dung lượng lưu trữ;
- tạo thư mục dạng cây;
- tải file lên hoặc lưu liên kết ngoài;
- tìm kiếm, gắn nhãn, đánh dấu sao và đưa file vào thùng rác;
- chia sẻ file bằng link hoặc chia sẻ trực tiếp cho người dùng khác;
- kiểm soát quyền xem và tải file;
- ghi lại lịch sử hoạt động;
- xử lý các việc lâu như quét file hoặc dọn thùng rác ở chế độ nền.

Ở trạng thái hiện tại, **Dashboard là luồng web duy nhất đã được nối đầy đủ**.
Models, forms, serializers và permissions đã có nhiều phần, nhưng API upload/chia
sẻ, AJAX và Celery chưa có URL/view/task để chạy.

## 2. Bức tranh tổng thể

```text
Trình duyệt
   |
   | GET /
   v
MiniDrive/urls.py
   |
   v
drive/urls.py
   |
   v
DashboardView.get_context_data()
   |                     |
   | truy vấn            | tạo context
   v                     v
SQLite <- Django ORM -> dashboard.html -> HTML trả về trình duyệt
```

Ba lớp quan trọng nhất:

1. **Model** mô tả dữ liệu và quy tắc luôn phải đúng.
2. **View** nhận request, gọi model/query và chuẩn bị dữ liệu trả về.
3. **Template** nhận context từ view rồi tạo HTML.

Khi xây API, serializer đứng giữa request JSON/file upload và model. Authentication
xác định người gửi request là ai; permission quyết định người đó được làm gì.

## 3. Bản đồ thư mục

| Đường dẫn | Vai trò |
|---|---|
| `manage.py` | Điểm vào cho lệnh Django như `runserver`, `test`, `migrate` |
| `MiniDrive/settings.py` | Cấu hình app, database, template, DRF, static và media |
| `MiniDrive/urls.py` | URL cấp dự án; nối `/admin/` và toàn bộ URL của app `drive` |
| `drive/models.py` | Dữ liệu, quan hệ, validation, QuerySet và Manager |
| `drive/forms.py` | Validation dành cho form HTML |
| `drive/serializers.py` | Chuyển đổi và validation dữ liệu dành cho REST API |
| `drive/authentication.py` | Đổi tiền tố token của DRF từ `Token` thành `Bearer` |
| `drive/permissions.py` | Quyền trên từng đối tượng file |
| `drive/views.py` | Hiện chỉ chứa `DashboardView` |
| `drive/urls.py` | Hiện chỉ ánh xạ `/` tới Dashboard |
| `drive/admin.py` | Đăng ký 7 model vào Django admin |
| `drive/tests.py` | 5 test cho custom manager và Dashboard |
| `templates/base.html` | Khung HTML dùng chung |
| `templates/dashboard.html` | Hiển thị dung lượng, tìm kiếm, root folder và root file |
| `drive/migrations/0001_initial.py` | Lịch sử tạo schema database ban đầu |

`main.py` ở ngoài thư mục MiniDrive chỉ là file mẫu do PyCharm tạo. Nó không tham gia
vào ứng dụng Django.

## 4. Hướng dẫn chạy để nhìn thấy kết quả

### Bước 1: kiểm tra dự án

Từ thư mục gốc repository, chạy:

```bash
./.venv/bin/python MiniDrive/manage.py check
./.venv/bin/python MiniDrive/manage.py test drive
```

Kết quả hiện tại phải là `System check identified no issues` và `Ran 5 tests ... OK`.

### Bước 2: chuẩn bị database

```bash
./.venv/bin/python MiniDrive/manage.py migrate
```

Nếu chưa có tài khoản quản trị:

```bash
./.venv/bin/python MiniDrive/manage.py createsuperuser
```

### Bước 3: chạy server

```bash
./.venv/bin/python MiniDrive/manage.py runserver
```

Mở `http://127.0.0.1:8000/admin/login/`, đăng nhập, sau đó mở
`http://127.0.0.1:8000/` để xem Dashboard.

Dashboard dùng `LoginRequiredMixin`, nhưng dự án chưa khai báo URL
`/accounts/login/`. Vì thế truy cập `/` khi chưa đăng nhập sẽ chuyển hướng tới một
URL đăng nhập chưa tồn tại. Đăng nhập qua admin là cách thử tạm thời, không phải luồng
đăng nhập cuối cùng cần xây.

## 5. Mô hình dữ liệu

```text
User 1 --- 1 Profile
  |
  +--- N Folder --- N Folder con
  |
  +--- N FileItem N --- N Label
            |
            +--- N ShareLink
            +--- N FileShare --- 1 User nhận
            +--- N ActivityLog
```

### `Profile`

Mở rộng `django.contrib.auth.models.User` bằng quan hệ một-một.

- `storage_quota_gb`: hạn mức, mặc định 5 GB.
- `used_storage_bytes`: dung lượng đã dùng.
- `is_suspended`: khóa khả năng upload.
- `quota_bytes`: đổi GB sang byte.
- `remaining_storage_bytes`: dung lượng còn lại, không trả số âm.
- `can_upload(size)`: chỉ cho phép khi tài khoản không bị khóa và chưa vượt quota.

Điểm cần nhớ: mã hiện tại **chưa tự cập nhật** `used_storage_bytes` khi tạo, xóa hoặc
khôi phục `FileItem`.

### `Label`

Nhãn dùng để phân loại file. `save()` tự tạo `slug` từ tên nếu slug đang trống và gọi
`full_clean()` trước khi ghi database. Tên chỉ gồm khoảng trắng bị từ chối.

### `Folder`

`parent` trỏ lại chính model `Folder`, tạo cấu trúc cây. Validation kiểm tra:

- tên không rỗng;
- folder không thể là cha của chính nó;
- parent phải cùng owner;
- parent không được nằm trong trash;
- không trùng tên trong cùng một parent của cùng owner.

`save()` đồng bộ `is_deleted` và `deleted_at`. Mã mới chỉ chặn `parent == self`, chưa
phát hiện vòng dài như A là cha B rồi B lại là cha A.

### `FileItem`

Đây là model trung tâm. Một bản ghi dùng **một trong hai** nguồn:

- file upload qua trường `file`; hoặc
- liên kết ngoài qua `external_url`.

Hai nguồn cùng có hoặc cùng không có đều sai. `save()` tự lấy kích thước file, đoán
MIME type, điền tên khi thiếu, đồng bộ trạng thái xóa rồi gọi `full_clean()`.

Các trạng thái xử lý:

| Giá trị | Ý nghĩa |
|---|---|
| `processing` | Đang chờ/đang xử lý |
| `ready` | Sẵn sàng sử dụng |
| `infected` | Phát hiện file nguy hiểm |
| `blocked` | Bị chặn |

### `ShareLink`

Tạo link chia sẻ bằng token ngẫu nhiên. Quyền là `view` hoặc `download`. Link hợp lệ
khi `is_active=True` và chưa hết hạn. Chỉ owner được tạo link; file trong trash,
`infected` hoặc `blocked` không được chia sẻ.

### `FileShare`

Biểu diễn chia sẻ trực tiếp từ `shared_by` tới `shared_with`, với quyền `viewer` hoặc
`editor`. Validation cấm tự chia sẻ, cấm chia sẻ file trong trash và yêu cầu
`shared_by` là owner.

Lưu ý: model này có `clean()` nhưng không override `save()` để gọi `full_clean()`.
Vì vậy `FileShare.objects.create(...)` không tự chạy các validation trên.

### `ActivityLog`

Lưu dấu vết các hành động `upload`, `delete`, `restore`, `share`, `move`, `scan`,
`expire`, `purge`. Quan hệ dùng `SET_NULL`, nên log vẫn còn nếu user/file/folder bị
xóa khỏi database.

## 6. QuerySet và Manager: phần bạn đang học

### QuerySet là gì?

QuerySet đại diện cho một câu truy vấn có thể nối tiếp nhiều bước. Django chưa chạy
SQL ngay khi bạn nối các hàm; nó thường chỉ chạy khi kết quả được sử dụng.

```python
files = FileItem.objects.active().search("report").size_between(0, 5_000_000)
```

Mỗi method trả về QuerySet, nên có thể chain như câu trên.

### Manager là gì?

Manager là cổng bắt đầu truy vấn, thường là `Model.objects`. Method thuộc QuerySet
phù hợp khi nó lọc và trả về một tập cùng loại để tiếp tục chain. Method thuộc Manager
phù hợp cho báo cáo hoặc điểm vào ở cấp model.

### Những method hiện có

| Cách gọi | Kết quả |
|---|---|
| `Folder.objects.roots()` | Folder gốc và chưa xóa |
| `FileItem.objects.active()` | File chưa xóa |
| `FileItem.objects.trash()` | File đã xóa |
| `FileItem.objects.search(keyword)` | Tìm trong tên, mô tả hoặc tên label |
| `FileItem.objects.size_between(min, max)` | Lọc theo khoảng kích thước |
| `FileItem.objects.due_for_purge(days=30)` | File trong trash quá số ngày quy định |
| `FileItem.objects.storage_summary_by_user()` | Tổng byte và số file theo user |
| `FileItem.objects.file_type_summary()` | Tổng byte và số file theo MIME type |
| `FileItem.objects.top_labels(limit=5)` | Các label được dùng nhiều nhất |
| `ShareLink.objects.active()` | Link bật và chưa hết hạn |
| `ShareLink.objects.expired()` | Link đã hết hạn |

`FolderQuerySet.as_manager()` đưa method `roots()` lên `Folder.objects`.
`Manager.from_queryset(FileItemQuerySet)` vừa giữ các method lọc để chain, vừa cho
phép bổ sung các báo cáo ở `FileItemManager`.

`search()` cần `.distinct()` vì join quan hệ nhiều-nhiều với label có thể tạo nhiều
dòng SQL cho cùng một file.

## 7. Một request Dashboard đi qua Django như thế nào?

1. Trình duyệt gửi `GET /`.
2. `MiniDrive/urls.py` chuyển request sang `drive.urls`.
3. `drive/urls.py` chọn `DashboardView.as_view()`.
4. `as_view()` tạo callable; `dispatch()` của class-based view chọn method xử lý theo
   HTTP verb. Vì đây là GET và `TemplateView` đã có `get()`, luồng đi vào phần render
   template.
5. `LoginRequiredMixin` kiểm tra session. Chưa đăng nhập thì redirect.
6. `get_context_data()` lấy `q`, user hiện tại, root folder, root file và tổng dung
   lượng file đang hoạt động.
7. View đưa dữ liệu vào dictionary `context`.
8. `dashboard.html` dùng vòng lặp và biến template để tạo HTML.

Dashboard chỉ hiển thị dữ liệu của `request.user`. Khi tìm kiếm, nó tìm root file theo
tên/mô tả/label và root folder theo tên. Dung lượng được tính trên tất cả file active
của user, kể cả file nằm trong folder con.

## 8. Validation nằm ở đâu?

### Model validation

`clean()` chứa quy tắc dữ liệu ở cấp domain. `full_clean()` lần lượt kiểm tra field,
gọi `clean()` và kiểm tra uniqueness. Django **không tự gọi `full_clean()` ở mọi lần
`save()`**; các model `Label`, `Folder`, `FileItem`, `ShareLink` trong dự án tự gọi nó.

### Form validation

Form dành cho HTML. Trình tự chính khi gọi `form.is_valid()`:

1. chuyển dữ liệu đầu vào về kiểu Python;
2. chạy validator của field;
3. chạy `clean_<field>()` cho một field;
4. chạy `clean()` cho quy tắc liên quan nhiều field;
5. với `ModelForm`, chạy thêm model validation.

`clean_<field>()` trả lại giá trị đã chuẩn hóa. `clean()` nhìn được nhiều field và có
thể dùng `add_error()` để gắn lỗi đúng chỗ.

Không nên dùng `fields = "__all__"` vì field mới thêm vào model có thể bất ngờ xuất
hiện trên form, kể cả field nội bộ hoặc nhạy cảm.

### Serializer validation

Serializer phục vụ API: nhận JSON/multipart, validate, chuyển sang kiểu Python và tạo
JSON response. Form phục vụ HTML và tích hợp widget, CSRF, thông báo lỗi trong
template. Hai lớp có mục đích khác nhau dù cú pháp validation khá giống nhau.

Hiện có:

- `FolderSerializer`: tạo folder thuộc user từ request.
- `FileListSerializer`: định dạng dữ liệu khi liệt kê file.
- `FileUploadSerializer`: giới hạn 20 MB; cho phép txt, pdf, png, jpg/jpeg, csv,
  xlsx, zip; chặn exe, bat, sh; kiểm tra quota và folder.
- `FileUpdateSerializer`: sửa metadata của file active thuộc owner.
- `ShareLinkSerializer`: tạo link hợp lệ cho file của owner.
- `ActivityLogSerializer`: định dạng log để đọc.

Các serializer này chưa được một API view nào sử dụng.

## 9. Authentication và Permission

### Authentication

Authentication trả lời: **request này là của ai?**

`BearerTokenAuthentication` kế thừa DRF `TokenAuthentication` và đổi keyword thành
`Bearer`. Header dự kiến:

```http
Authorization: Bearer <token>
```

### Permission

Permission trả lời: **người đó có được thực hiện hành động này không?**

- `IsOwnerOrStaff`: cho owner hoặc staff.
- `CanViewFile`: cho staff, owner, hoặc người có share token hợp lệ; chặn file đã xóa,
  infected và blocked.
- `CanDownloadFile`: giống quyền xem nhưng share token phải có permission `download`.

Object-level permission cần thiết vì “được vào endpoint file” không có nghĩa là
“được xem mọi file”. DRF chỉ chạy `has_object_permission()` khi view lấy object và
gọi luồng kiểm tra object permission, thường qua `get_object()`.

Hiện chưa có API view gọi ba permission class này. Cấu hình DRF toàn cục còn dùng
`AllowAny`, nên endpoint mới phải khai báo permission phù hợp hoặc đổi chính sách mặc
định.

## 10. ORM và các khái niệm cần nhớ

### `values()` và `values_list()`

```python
FileItem.objects.values("id", "name")
# <QuerySet [{"id": 1, "name": "a.pdf"}]>

FileItem.objects.values_list("id", "name")
# <QuerySet [(1, "a.pdf")]>

FileItem.objects.values_list("id", flat=True)
# <QuerySet [1, 2, 3]>
```

`values()` trả dictionary; `values_list()` trả tuple và thường gọn hơn.

### `F()` khi tăng bộ đếm

Không nên đọc `download_count`, cộng 1 trong Python rồi save vì hai request đồng thời
có thể ghi đè nhau. Cập nhật trong database an toàn hơn:

```python
from django.db.models import F

FileItem.objects.filter(pk=file_id).update(
    download_count=F("download_count") + 1
)
```

### `select_related()` và `prefetch_related()`

- `select_related()` dùng SQL JOIN, phù hợp ForeignKey/OneToOne như `file.owner` và
  `file.folder`.
- `prefetch_related()` chạy truy vấn riêng rồi ghép trong Python, phù hợp ManyToMany
  và quan hệ ngược như `file.labels` hoặc `folder.children`.

Ví dụ tối ưu danh sách file:

```python
files = (
    FileItem.objects.active()
    .select_related("owner", "folder")
    .prefetch_related("labels")
)
```

### `update()`, `bulk_update()` và `bulk_create()`

- `QuerySet.update()` cập nhật trực tiếp nhiều dòng bằng SQL.
- `bulk_update(objects, fields)` cập nhật danh sách object đã sửa trong Python.
- `bulk_create(objects)` chèn nhiều object.

Các thao tác bulk không gọi `save()` cho từng object và không phát các signal save
thông thường. Vì thế chúng cũng bỏ qua logic tự động trong custom `save()` của dự án,
như `full_clean()`, điền MIME type hoặc đồng bộ `deleted_at`. Chỉ dùng khi bạn chủ
động bảo đảm dữ liệu hợp lệ.

## 11. Admin

`drive/admin.py` hiện chỉ đăng ký cả 7 model nên chúng xuất hiện với giao diện mặc
định. Muốn chọn cột, tìm kiếm hoặc readonly, tạo `ModelAdmin`:

```python
@admin.register(FileItem)
class FileItemAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "status", "size_bytes", "created_at")
    search_fields = ("name", "owner__username")
    readonly_fields = ("size_bytes", "mime_type", "download_count")
```

Admin action là thao tác chạy trên nhiều dòng được chọn, ví dụ đánh dấu các file là
blocked. Một model readonly hoàn toàn thường cần chặn quyền add/change/delete và chỉ
cho view; chỉ đặt `readonly_fields` chưa chặn xóa hoặc thêm.

## 12. Background task và Celery

Background task là việc được đưa ra khỏi request web để worker xử lý sau. Request chỉ
xếp việc vào hàng đợi rồi trả response nhanh cho người dùng.

```text
Django view -> Broker (hàng đợi) -> Celery worker -> cập nhật database
```

- **Celery** là thư viện điều phối task nền.
- **Broker** như Redis/RabbitMQ giữ thông điệp task đang chờ.
- **Worker** là process lấy task từ broker và thực thi.
- `task.delay(a, b)` là cú pháp ngắn để enqueue với đối số.
- `task.apply_async(args=[a, b], countdown=10, queue="scan")` cho phép cấu hình thời
  gian chạy, queue, retry và các tùy chọn khác.

Scan virus, gửi email và purge trash nên chạy nền vì có thể chậm hoặc phụ thuộc dịch
vụ ngoài. Nếu worker không chạy, task thường vẫn nằm trong broker và chưa được xử lý;
web app không nên báo rằng công việc đã hoàn thành.

Celery và broker **chưa được cài đặt hoặc cấu hình trong repository hiện tại**. Đây
là phần thiết kế cho bước sau, không phải chức năng đang chạy.

## 13. AJAX và CSRF

AJAX cho phép JavaScript gửi request mà không tải lại cả trang. Upload bằng AJAX có
thể hiển thị tiến độ, lỗi ngay cạnh input và cập nhật danh sách sau khi thành công.
Upload form truyền thống vẫn hợp lệ nếu bài tập không yêu cầu trải nghiệm này.

Với Django session authentication, request thay đổi dữ liệu phải gửi CSRF token,
thường qua header `X-CSRFToken`. JavaScript đọc response JSON, duyệt object lỗi theo
field và đưa từng message vào giao diện.

Repository hiện chưa có JavaScript upload, API upload hay đoạn xử lý CSRF bằng AJAX.
Vì vậy đây cũng là phần cần làm tiếp, không phải phần đã hoàn thành.

## 14. Điều đã chạy và điều chưa được nối

| Thành phần | Trạng thái hiện tại |
|---|---|
| Models và migration ban đầu | Có và database tạo được |
| Custom QuerySet/Manager | Có, 3 test kiểm tra method tồn tại |
| Dashboard `/` | Có, 2 test kiểm tra login và phạm vi dữ liệu |
| Template Dashboard | Có, hiển thị và tìm kiếm cơ bản |
| Django admin | Có, cấu hình mặc định |
| Forms | Đã viết nhưng chưa có view/URL/template sử dụng |
| Serializers | Đã viết nhưng chưa có API view/URL sử dụng |
| Token authentication | Đã cấu hình nhưng chưa có endpoint cấp token trong URL |
| Object permissions | Đã viết nhưng chưa được API view sử dụng |
| Upload/chỉnh sửa/xóa/khôi phục/chia sẻ qua UI | Chưa nối |
| AJAX | Chưa có |
| Celery/background task | Chưa cài đặt hoặc cấu hình |

## 15. Các điểm cần cẩn thận khi làm tiếp

1. `Profile` chưa được tạo tự động khi tạo `User`. Upload serializer sẽ báo lỗi nếu
   user không có profile.
2. `used_storage_bytes` chưa tự đồng bộ với file thật.
3. Folder chưa có database `UniqueConstraint`; validation bằng query vẫn có thể gặp
   race condition khi hai request tạo cùng lúc.
4. Cây folder chưa chặn chu trình nhiều cấp.
5. `FileShare.clean()` có thể bị bỏ qua do `save()` không gọi `full_clean()`.
6. Share token nằm trong query string có thể xuất hiện trong lịch sử trình duyệt và
   access log. Cần cân nhắc rủi ro khi triển khai thật.
7. `IsOwnerOrStaff` giả định object có thuộc tính `owner`; không dùng trực tiếp cho
   model chỉ có `created_by` hoặc `shared_by`.
8. `SECRET_KEY`, `DEBUG=True`, SQLite và `ALLOWED_HOSTS=[]` chỉ phù hợp lúc học/phát
   triển, không phải cấu hình production.
9. Cấu hình email đang dùng tên `MAILERS`, trong khi Django thông thường đọc
   `EMAIL_BACKEND`; cần sửa khi triển khai gửi email.
10. Validation đang lặp ở model, form và serializer. Hãy xác định quy tắc domain nào
    bắt buộc ở model và quy tắc trình bày nào thuộc form/API.

## 16. Lộ trình làm bài đề xuất

Làm theo từng lát cắt có thể chạy và test được:

1. **Hoàn thiện đăng nhập web:** thêm URL/template login và logout; test redirect.
2. **Bảo đảm Profile tồn tại:** tạo cùng user hoặc dùng signal có test rõ ràng.
3. **Nối FolderForm:** list, create, update và soft-delete folder theo owner.
4. **Nối upload file:** API hoặc form tạo `FileItem`, cập nhật quota trong transaction,
   rồi test file quá 20 MB, sai extension và folder của người khác.
5. **Nối chỉnh sửa và trash:** dùng `FileMetadataForm`/serializer, restore và purge;
   test `deleted_at` và dung lượng.
6. **Nối chia sẻ:** endpoint tạo link, xem và download; áp permission object-level;
   tăng `download_count` bằng `F()`.
7. **Thêm AJAX:** upload và hiển thị lỗi server trên Dashboard.
8. **Thêm Celery:** scan, email, expire link và purge trash; test enqueue riêng với
   logic task.
9. **Tùy chỉnh admin:** cột, filter, readonly và admin actions.
10. **Tối ưu query:** đo số truy vấn rồi thêm `select_related()` và
    `prefetch_related()` đúng chỗ.

Sau mỗi bước, viết test trước cho hành vi mong muốn, chạy toàn bộ test, rồi mới chuyển
sang bước tiếp theo.

## 17. Cách học để thật sự nhớ

Với mỗi phần, dùng vòng lặp sau:

1. Đọc một section trong sổ tay.
2. Đóng tài liệu và tự vẽ lại luồng bằng 5-7 dòng.
3. Mở đúng file mã nguồn, chỉ ra dòng nào thực hiện từng ý.
4. Chạy Django shell hoặc test để quan sát kết quả.
5. Tự sửa một ví dụ nhỏ, dự đoán kết quả trước khi chạy.
6. Ghi lại một lỗi đã gặp và nguyên nhân của nó.

### Bài tập tự kiểm tra đầu tiên

Mở Django shell:

```bash
./.venv/bin/python MiniDrive/manage.py shell
```

Sau đó tự trả lời và thử nghiệm:

1. Vì sao `FileItem.objects.active().search("pdf")` chain được?
2. Bỏ `.distinct()` trong `search()` có thể tạo lỗi gì?
3. Vì sao Dashboard lọc `owner` ở cả folder và file?
4. File trong folder con có được tính vào `storage_used_bytes` không?
5. Vì sao `bulk_update()` nguy hiểm với custom `save()` hiện tại?
6. Serializer tồn tại nhưng vì sao vẫn chưa gọi được API upload?
7. Permission class tồn tại nhưng khi nào DRF mới thực sự chạy nó?

Nếu bạn giải thích được bảy câu này mà không nhìn tài liệu, bạn đã hiểu phần lõi đang
chạy của bài tập.

## 18. Bảng từ khóa ôn nhanh

| Từ khóa | Câu nhớ ngắn |
|---|---|
| Model | Dữ liệu và quy tắc domain |
| Migration | Lịch sử thay đổi schema database |
| QuerySet | Tập truy vấn có thể chain và thường lazy |
| Manager | Cổng bắt đầu truy vấn ở cấp model |
| Form | Nhận và validate dữ liệu HTML |
| Serializer | Nhận/xuất và validate dữ liệu API |
| Authentication | Bạn là ai? |
| Permission | Bạn được làm gì? |
| View | Điều phối một request |
| Context | Dữ liệu view đưa cho template |
| Template | Biến context thành HTML |
| Broker | Hàng đợi task |
| Worker | Process thực thi task nền |
| AJAX | Gửi request bằng JavaScript mà không reload cả trang |
| CSRF | Bảo vệ request dùng phiên đăng nhập khỏi giả mạo từ website khác |

## Tài liệu liên quan

- [README và danh sách câu hỏi ôn tập](../README.md)
- [Mã model](../drive/models.py)
- [Mã Dashboard](../drive/views.py)
- [Các test hiện có](../drive/tests.py)
