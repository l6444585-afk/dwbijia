# 平台 API 接入指南

本系统支持 6 个平台的数据采集。配置了官方 API 后，系统会优先使用 API 获取数据（更快更稳定），未配置时自动降级到 H5 页面解析。

---

## 1. 淘宝 - 淘宝联盟 API

| 项目 | 说明 |
|------|------|
| 注册地址 | https://open.taobao.com/ |
| 申请条件 | 需要支付宝实名认证的淘宝账号 |
| 所需 API | **淘宝客商品查询** (`taobao.tbk.item.get`) |
| 适用场景 | 商品搜索、价格查询 |

**申请步骤：**
1. 登录 [淘宝开放平台](https://open.taobao.com/)，用淘宝账号注册开发者
2. 创建应用，选择"网站应用"，填写应用信息
3. 进入 [淘宝联盟](https://pub.alimama.com/) 注册推广者账号
4. 在开放平台申请 `taobao.tbk.item.get` 等淘宝客 API 权限
5. 获取 AppKey 和 AppSecret

**环境变量：**
```env
TAOBAO_API_KEY=你的AppKey
TAOBAO_API_SECRET=你的AppSecret
TAOBAO_API_URL=https://eco.taobao.com/router/rest
```

---

## 2. 京东 - 京东联盟 API

| 项目 | 说明 |
|------|------|
| 注册地址 | https://union.jd.com/ (联盟) / https://open.jd.com/ (开放平台) |
| 申请条件 | 京东账号，个人或企业均可 |
| 所需 API | **商品查询** (`jd.union.open.goods.query`) |
| 适用场景 | 商品搜索、价格和优惠券查询 |

**申请步骤：**
1. 登录 [京东联盟](https://union.jd.com/)，注册成为推广者
2. 进入 [京东开放平台](https://open.jd.com/)，创建应用
3. 申请京东联盟 API 权限（`jd.union.open.goods.query`）
4. 获取 AppKey 和 AppSecret
5. API 签名方式：`MD5(secret + 参数排序拼接 + secret)`，系统已内置签名逻辑

**环境变量：**
```env
JD_API_KEY=你的AppKey
JD_API_SECRET=你的AppSecret
JD_API_URL=https://api.jd.com/routerjson
```

---

## 3. 拼多多 - 多多客 API

| 项目 | 说明 |
|------|------|
| 注册地址 | https://open.pinduoduo.com/ |
| 申请条件 | 拼多多账号，需完成实名认证 |
| 所需 API | **多多客商品查询** (`pdd.ddk.goods.search`) |
| 适用场景 | 商品搜索、团购价/单买价查询 |

**申请步骤：**
1. 登录 [拼多多开放平台](https://open.pinduoduo.com/)，注册开发者
2. 进入 [多多进宝](https://jinbao.pinduoduo.com/) 注册推广者
3. 在开放平台创建应用，选择"多多客"类型
4. 申请商品搜索相关 API 权限
5. 获取 client_id 和 client_secret

**环境变量：**
```env
PDD_API_KEY=你的client_id
PDD_API_SECRET=你的client_secret
PDD_API_URL=https://gw-api.pinduoduo.com/api/router
```

---

## 4. 1688 - 阿里巴巴开放平台 API

| 项目 | 说明 |
|------|------|
| 注册地址 | https://open.1688.com/ |
| 申请条件 | 企业支付宝认证的 1688 账号（**需要营业执照**） |
| 所需 API | **商品搜索** (`alibaba.trade`) 或 **跨境供货** 相关 API |
| 适用场景 | 批发商品搜索、阶梯价查询 |

**申请步骤：**
1. 登录 [1688 开放平台](https://open.1688.com/)，用企业账号注册开发者
2. 创建应用，选择合适的应用类型
3. 申请商品搜索和详情查询 API 权限
4. 获取 AppKey 和 AppSecret
5. 注意：1688 开放平台对个人开发者限制较多，部分 API 需要企业资质

**环境变量：**
```env
ALI1688_API_KEY=你的AppKey
ALI1688_API_SECRET=你的AppSecret
ALI1688_API_URL=https://gw.open.1688.com/openapi
```

---

## 5. 得物

| 项目 | 说明 |
|------|------|
| 公开 API | **无** |
| 当前方案 | H5 页面接口 (`app.dewu.com/api/v1/h5/`) + HTML 解析 |

得物目前没有面向第三方的公开开发者平台和 API。系统通过以下方式获取数据：
- H5 API 搜索：`POST https://app.dewu.com/api/v1/h5/search/fire/search/list`
- H5 API 详情：`GET https://app.dewu.com/api/v1/h5/index/fire/flow/detail`
- 页面 HTML 解析（兜底）

如果你有第三方数据服务商提供的得物数据接口，可以配置：
```env
DEWU_API_KEY=第三方服务的API密钥
DEWU_API_SECRET=第三方服务的Secret
DEWU_API_URL=第三方服务的API地址
```

---

## 6. 识货

| 项目 | 说明 |
|------|------|
| 公开 API | **无** |
| 当前方案 | H5 页面接口 (`m.shihuo.com/gateway/`) + HTML 解析 |

识货目前没有面向第三方的公开开发者平台和 API。系统通过以下方式获取数据：
- H5 API 搜索：`POST https://m.shihuo.com/gateway/search`
- H5 API 详情：`GET https://m.shihuo.com/gateway/product/detail`
- 页面 HTML 解析（兜底）

如果你有第三方数据服务商提供的识货数据接口，可以配置：
```env
SHIHUO_API_KEY=第三方服务的API密钥
SHIHUO_API_SECRET=第三方服务的Secret
SHIHUO_API_URL=第三方服务的API地址
```

---

## 快速配置

将以下内容复制到项目根目录的 `.env` 文件中，填入你的密钥：

```env
# ====== 淘宝联盟 API ======
TAOBAO_API_KEY=
TAOBAO_API_SECRET=
TAOBAO_API_URL=https://eco.taobao.com/router/rest

# ====== 京东联盟 API ======
JD_API_KEY=
JD_API_SECRET=
JD_API_URL=https://api.jd.com/routerjson

# ====== 拼多多多多客 API ======
PDD_API_KEY=
PDD_API_SECRET=
PDD_API_URL=https://gw-api.pinduoduo.com/api/router

# ====== 1688 开放平台 API ======
ALI1688_API_KEY=
ALI1688_API_SECRET=
ALI1688_API_URL=https://gw.open.1688.com/openapi

# ====== 得物（无公开API，第三方服务可选） ======
# DEWU_API_KEY=
# DEWU_API_SECRET=
# DEWU_API_URL=

# ====== 识货（无公开API，第三方服务可选） ======
# SHIHUO_API_KEY=
# SHIHUO_API_SECRET=
# SHIHUO_API_URL=
```

**说明：**
- 留空的 KEY/SECRET 不影响系统运行，系统会自动降级到 H5 接口和页面解析
- 淘宝、京东、拼多多建议优先申请官方 API，数据更稳定
- 1688 需要企业资质，个人开发者可先用 H5 接口
- 得物和识货无公开 API，保持注释状态即可
