# 背景数据库服务重构方案

## 一、项目背景

### 1.1 现状

当前系统中背景数据库相关功能分布在三个服务中：

| 服务 | 角色 | 数据库表前缀 | 字段风格 |
|------|------|-------------|---------|
| **transfer-pro** | 背景数据库数据源（被引用方） | `t_` | 简洁 snake_case，单一语言字段 |
| **ec-lcaadmin-pro** | LCA管理后台 | `h_` | 详细 snake_case，中英文分离字段 |
| **lca_calculate-pro** | LCA计算引擎 | `t_`（与transfer-pro同库） | 简洁 snake_case，与transfer-pro一致 |

### 1.2 目标

1. 将 ec-lcaadmin-pro 中的背景数据库模块拆成**按版本动态表**
2. manager-pro 中引用 transfer-pro 的代码**替换为引用 ec-lcaadmin-pro**，并补全缺失接口
3. lca_calculate-pro 中背景数据库引用**切换为 ec-lcaadmin-pro**

### 1.3 核心难点

**两边数据库字段命名方式差异很大**，主要体现在：

- 表名前缀不同（`t_` vs `h_`）
- 主键命名不同（`id` vs 业务语义主键如 `background_db_manage_id`）
- 多语言支持不同（单一字段 vs `*_cn`/`*_en` 拆分）
- 字段类型不同（String vs Long）
- 审计字段完整度不同

---

## 二、数据库字段映射对照

### 2.1 Process（工艺过程）

| transfer-pro (`t_processes`) | ec-lcaadmin-pro (`h_background_db_manage`) | 差异类型 |
|------------------------------|-------------------------------------------|---------|
| `id` (Long) | `background_db_manage_id` (Long) | 主键重命名 |
| `uuid` (String) | `uuid` (String) | ✅ 一致 |
| `name` (String) | `name_en` / `name_cn` (String) | 拆分为中英文 |
| `description_general` (String) | `description_general_en` / `description_general_cn` | 拆分+重命名 |
| `category` (String) | `category` (String) | ✅ 一致 |
| `version` (String) | `version_id` (Long) | 类型+名称变化 |
| `start_date` (Date) | `start_date` (Date) | ✅ 一致 |
| `end_date` (Date) | `end_date` (Date) | ✅ 一致 |
| `location` (String) | `location_id` (Long) | 类型变化，需JOIN查询 |
| `description_location` (String) | `description_location` / `description_location_cn` | 拆分 |
| `description_technology` (String) | `description_technology` / `description_technology_cn` | 拆分 |
| `process_uuid` (String) | `up_uuid` (String) | 重命名 |
| `unit` (String) | `unit_id` (Long) | 类型变化，需JOIN查询 |
| `flow_product` (String) | `flow_fac_header_id` (Long) | 名称+类型变化 |
| `allocation_method` (Long) | `default_allocation_method` (String) | 名称+类型变化 |
| ❌ 无 | `carbon_footprint_unit`, `carbon_footprint_value` | 新增字段 |
| ❌ 无 | `industry`, `library`, `quality_entry` 等 | 新增字段 |
| `create_time` (Date) | `create_time` / `create_id` / `update_time` / `update_id` / `delete_time` / `delete_id` / `is_deleted` | 审计字段扩展 |

### 2.2 Flow（基本流）

| transfer-pro (`t_flows`) | ec-lcaadmin-pro (通过 `h_background_db_flow_relation` 关联) | 差异类型 |
|--------------------------|--------------------------------------------------------|---------|
| `id` (Long) | 通过 `flow_fac_header_id` 间接关联 | 关联方式变化 |
| `uuid` (String) | 需要查询关联表 | 间接获取 |
| `name` (String) | 需要查询关联表 | 间接获取 |
| `flow_type` (String) | 需新增字段或从其他表获取 | 可能缺失 |
| `category` (String) | 需要查询关联表 | 间接获取 |
| `unit_id` (String) | 需要查询关联表 | 间接获取 |
| `name_cn` (String) | 需要查询关联表 | 间接获取 |
| `commonly` (Integer) | ❌ 无 | 需新增 |
| `basic_flow_id` (Long) | ❌ 无 | 需新增 |

### 2.3 Location（地理位置）

| transfer-pro (`t_locations`) | ec-lcaadmin-pro (需新建或引用) | 差异类型 |
|-------------------------------|-------------------------------|---------|
| `id` (Long) | `id` (Long) | ✅ 一致 |
| `code` (String) | `code` (String) | ✅ 一致 |
| `latitude` (Double) | `latitude` (Double) | ✅ 一致 |
| `longitude` (Double) | `longitude` (Double) | ✅ 一致 |
| `name` (String) | `name` (String) | ✅ 一致 |
| `description` (String) | `description` (String) | ✅ 一致 |

### 2.4 Unit（单位）

| transfer-pro (`t_units`) | ec-lcaadmin-pro (需确认) | 差异类型 |
|--------------------------|--------------------------|---------|
| `id` (Long) | 待确认 | 待确认 |
| `uuid` (String) | 待确认 | 待确认 |
| `name` (String) | 待确认 | 待确认 |
| `conversion_factor` (BigDecimal) | 待确认 | 待确认 |
| `unit_group` (String) | 待确认 | 待确认 |
| `synonyms` (String) | 待确认 | 待确认 |
| `is_show` (Integer) | 待确认 | 待确认 |
| `is_deleted` (Integer) | 待确认 | 待确认 |

### 2.5 BackgroundDbFlowRelation（背景数据基本流关联）

ec-lcaadmin-pro 独有表，transfer-pro 中无对应表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `db_flow_relation_id` | Long | 主键 |
| `amount` | BigDecimal | 数值 |
| `background_db_manage_id` | Long | 背景数据id |
| `flow_fac_header_id` | Long | 流id |
| `version_id` | Long | 版本id |
| `uuid` | String | UUID |
| `create_id` / `create_time` | Long / Date | 创建信息 |
| `update_id` / `update_time` | Long / Date | 更新信息 |
| `delete_id` / `delete_time` | Long / Date | 删除信息 |
| `is_deleted` | Integer | 删除标记 |

---

## 三、TransferProFeign 接口清单与覆盖分析

### 3.1 manager-pro 中 TransferProFeign 调用统计

共 **17个Biz文件** 注入了 `TransferProFeign`，约 **166处调用**。

### 3.2 接口覆盖情况

| 接口方法 | 调用次数 | ec-lcaadmin-pro 是否已有 | 需要补全 |
|----------|---------|------------------------|---------|
| `getAllUnits(versionId)` | ~20次 | ✅ 已有 UnitService | 否 |
| `getAllVersions()` | ~10次 | ✅ 已有 VersionService | 否 |
| `getVersionById(id)` | ~5次 | ✅ 已有 VersionService | 否 |
| `getAllCategories(versionId)` | ~5次 | ✅ 已有 CategoriesService | 否 |
| `getAllLocations()` | ~8次 | ✅ 已有 LocationService | 否 |
| `getStandardUnitById(id, groupUuid)` | ~3次 | ✅ 已有 UnitService | 否 |
| `getStandardUnitBatchByIds(ids)` | ~8次 | ⚠️ 需补全 | 是 |
| `getUnitBatchByIds(ids)` | ~2次 | ⚠️ 需补全 | 是 |
| `getUnitById(id)` | ~1次 | ⚠️ 需补全 | 是 |
| `getUnitGroupList()` | ~1次 | ⚠️ 需补全 | 是 |
| `getImpactMethod()` | ~8次 | ⚠️ 需补全 | 是 |
| `getImpactCategory(version, ids)` | ~5次 | ⚠️ 需补全 | 是 |
| `getImpactCategoriesByMethodId(version, methodId)` | ~2次 | ⚠️ 需补全 | 是 |
| `getFlowsByStandardIds(version, ids)` | ~6次 | ⚠️ 需补全 | 是 |
| `getFLows(version)` | ~1次 | ⚠️ 需补全 | 是 |
| `getFLowList(version, req)` | ~1次 | ⚠️ 需补全 | 是 |
| `getMyCatFlowsByIds(version, ids)` | ~1次 | ⚠️ 需补全 | 是 |
| `getProcessByStandardUuids(version, uuids)` | ~6次 | ⚠️ 需补全 | 是 |
| `getMyCatProcessByIds(version, ids)` | ~6次 | ⚠️ 需补全 | 是 |
| `getMyCatProcessById(version, id)` | ~1次 | ⚠️ 需补全 | 是 |
| `getMyCatProcessByUuids(version, uuids)` | ~2次 | ⚠️ 需补全 | 是 |
| `queryProcessPageList(...)` | ~5次 | ⚠️ 需补全 | 是 |
| `getMyCatProcessInputPage(...)` | ~1次 | ⚠️ 需补全 | 是 |
| `getGenerateProcessByUuids(version, uuids)` | ~1次 | ⚠️ 需补全 | 是 |
| `addGenerateProcess(request)` | ~1次 | ⚠️ 需补全 | 是 |
| `editGenerateProcess(request)` | ~2次 | ⚠️ 需补全 | 是 |
| `generateProcessImpactAnalysis(uuid)` | ~2次 | ⚠️ 需补全 | 是 |
| `getImpactAnalysisList(uuids)` | ~3次 | ⚠️ 需补全 | 是 |
| `getGenerateProcessInput(...)` | ~1次 | ⚠️ 需补全 | 是 |
| `getLocationById(id)` | ~1次 | ⚠️ 需补全 | 是 |
| `getCategoryList(version, type)` | ~1次 | ⚠️ 需补全 | 是 |
| `getCategoryTreeByProcess(version)` | ~1次 | ⚠️ 需补全 | 是 |
| `getLocationsTree()` | ~1次 | ⚠️ 需补全 | 是 |
| `getMethodByFlows(version, flows)` | ~3次 | ⚠️ 需补全 | 是 |
| `getLciUnits(version, req)` | ~1次 | ⚠️ 需补全 | 是 |
| `getCategoriesListByUuIds(version, uuids)` | ~1次 | ⚠️ 需补全 | 是 |

**统计：已覆盖 5 个，需补全 31 个接口**

---

## 四、详细实施方案

### 阶段一：ec-lcaadmin-pro 背景数据库动态表改造

#### 4.1.1 改造范围

| 表名 | 实体类 | 说明 |
|------|--------|------|
| `h_background_db_manage` | BackgroundDbManage | 背景数据主表 |
| `h_background_db_flow_relation` | BackgroundDbFlowRelation | 背景数据基本流关联表 |
| `h_background_db_mapping` | BackgroundDbMapping | 流映射头表 |
| `h_background_db_mapping_line` | BackgroundDbMappingLine | 流映射行表 |
| `h_background_db_advertise` | BackgroundDbAdvertise | 背景数据广告表 |

#### 4.1.2 实现方案

参考 lca_calculate-pro 已有的动态表机制：

1. **创建版本常量类** `BackgroundDbVersionConstant`
2. **修改 MybatisPlusConfig** 添加动态表名解析器
3. **修改实体类** `@TableName` 支持动态表名
4. **修改 Mapper/Service/Controller** 增加版本参数传递
5. **数据库脚本** 按版本创建新表

动态表命名规则：`h_background_db_manage_{versionId}`

#### 4.1.3 工作量

| 工作项 | 时间 |
|--------|------|
| 引入动态表框架 | 0.5天 |
| 修改5张表实体 | 0.5天 |
| 修改Mapper/Service/Controller | 1天 |
| 数据库脚本+数据迁移 | 1天 |
| 测试验证 | 1天 |
| **小计** | **4天** |

---

### 阶段二：ec-lcaadmin-pro 补全缺失接口

#### 4.2.1 接口分类与实现优先级

**P0 - 核心接口（必须首先实现）**

| 接口 | 涉及实体 | 字段映射复杂度 | 预估时间 |
|------|---------|--------------|---------|
| `getProcessByStandardUuids` | BackgroundDbManage | 高（15+字段映射） | 0.5天 |
| `getMyCatProcessByIds` | BackgroundDbManage | 高 | 0.5天 |
| `getMyCatProcessByUuids` | BackgroundDbManage | 高 | 0.5天 |
| `queryProcessPageList` | BackgroundDbManage | 高（含分页+条件查询） | 0.5天 |
| `getFlowsByStandardIds` | BackgroundDbFlowRelation | 高（间接关联） | 0.5天 |
| `getFLows` | BackgroundDbFlowRelation | 高 | 0.5天 |
| `getFLowList` | BackgroundDbFlowRelation | 高（含分页） | 0.5天 |
| `getImpactMethod` | ImpactMethod | 中 | 0.25天 |
| `getImpactCategory` | ImpactCategory | 中 | 0.25天 |

**P1 - 重要接口**

| 接口 | 涉及实体 | 字段映射复杂度 | 预估时间 |
|------|---------|--------------|---------|
| `getGenerateProcessByUuids` | GenerateProcesses | 中 | 0.25天 |
| `addGenerateProcess` | GenerateProcesses | 中 | 0.25天 |
| `editGenerateProcess` | GenerateProcesses | 中 | 0.25天 |
| `generateProcessImpactAnalysis` | ProcessImpactAnalysis | 高 | 0.5天 |
| `getImpactAnalysisList` | ProcessImpactAnalysis | 中 | 0.25天 |
| `getGenerateProcessInput` | GenerateProcessInput | 中 | 0.25天 |
| `getStandardUnitBatchByIds` | Unit | 低 | 0.25天 |
| `getUnitBatchByIds` | Unit | 低 | 0.25天 |
| `getMethodByFlows` | ImpactMethod + ImpactCategory | 中 | 0.25天 |

**P2 - 辅助接口**

| 接口 | 涉及实体 | 字段映射复杂度 | 预估时间 |
|------|---------|--------------|---------|
| `getMyCatProcessById` | BackgroundDbManage | 中 | 0.25天 |
| `getMyCatProcessInputPage` | GenerateProcessInput | 中 | 0.25天 |
| `getMyCatFlowsByIds` | BackgroundDbFlowRelation | 中 | 0.25天 |
| `getUnitById` | Unit | 低 | 0.25天 |
| `getUnitGroupList` | TUnitGroup | 低 | 0.25天 |
| `getImpactCategoriesByMethodId` | ImpactCategory | 中 | 0.25天 |
| `getLocationById` | Locations | 低 | 0.25天 |
| `getCategoryList` | Categories | 低 | 0.25天 |
| `getCategoryTreeByProcess` | Categories | 中 | 0.25天 |
| `getLocationsTree` | Locations | 中 | 0.25天 |
| `getLciUnits` | Unit | 低 | 0.25天 |
| `getCategoriesListByUuIds` | Categories | 低 | 0.25天 |

#### 4.2.2 字段映射适配方案

**方案：在 ec-lcaadmin-pro Feign 层做适配转换**

核心适配逻辑示例：

```java
public class ProcessResponseAdapter {
    public static ProcessesResponse adapt(BackgroundDbManage manage) {
        ProcessesResponse response = new ProcessesResponse();
        response.setId(manage.getBackgroundDbManageId());
        response.setUuid(manage.getUuid());
        response.setName(LocaleUtil.getName(manage.getNameCn(), manage.getNameEn()));
        response.setDescriptionGeneral(LocaleUtil.getName(
            manage.getDescriptionGeneralCn(), manage.getDescriptionGeneralEn()));
        response.setCategory(manage.getCategory());
        response.setVersionId(String.valueOf(manage.getVersionId()));
        response.setStartDate(manage.getStartDate());
        response.setEndDate(manage.getEndDate());
        response.setLocation(manage.getLocationName());
        response.setUnit(manage.getUnitName());
        response.setFlowProduct(manage.getFlowUuid());
        response.setProcessUuid(manage.getUpUuid());
        response.setAllocationMethod(
            Long.valueOf(manage.getDefaultAllocationMethod()));
        return response;
    }
}
```

#### 4.2.3 工作量

| 工作项 | 时间 |
|--------|------|
| 创建 DTO/Response 对象（31个接口） | 1.5天 |
| 实现字段映射工具类 | 1天 |
| P0 核心接口实现（9个） | 3.5天 |
| P1 重要接口实现（9个） | 2.5天 |
| P2 辅助接口实现（13个） | 2天 |
| 接口单元测试 | 2天 |
| **小计** | **12.5天** |

---

### 阶段三：manager-pro 替换 TransferProFeign

#### 4.3.1 改造范围

**涉及文件清单（17个Biz文件）**：

| 文件 | TransferProFeign 调用数 |
|------|----------------------|
| AiBiz.java | ~5 |
| OperateBiz.java | ~8 |
| LcaUpDataBiz.java | ~15 |
| DataConfigurationBiz.java | ~10 |
| CaseEvaluationDetailBiz.java | ~12 |
| CaseCalculationBiz.java | ~20 |
| OpenApiBiz.java | ~8 |
| BrandBiz.java | ~3 |
| MProductBiz.java | ~10 |
| MProcessElementBiz.java | ~8 |
| ProductChartBiz.java | ~5 |
| ProductConfigurationBiz.java | ~12 |
| ToIlcdBiz.java | ~15 |
| ReportBiz.java | ~8 |
| ProductComparisonBiz.java | ~5 |
| CorporateBackDataBiz.java | ~8 |
| CaseCalculationDetailBiz.java | ~14 |

#### 4.3.2 改造步骤

1. **pom.xml 依赖调整**
    - 移除 `ecdigit-transfer-pro-feign`
    - 确认 `ecdigit-lcaadmin-pro-feign` 版本

2. **注入替换**
   ```java
   // 替换前
   @Autowired
   private TransferProFeign transferProFeign;
   
   // 替换后
   @Autowired
   private LcaadminProFeign lcaadminProFeign;
   ```

3. **方法调用替换**
   ```java
   // 替换前
   transferProFeign.getAllUnits(versionId);
   
   // 替换后
   lcaadminProFeign.getAllUnits(versionId);
   ```

4. **返回值适配**（如果 Response 对象有差异）
    - 如果 ec-lcaadmin-pro Feign 层已做适配，此处无需额外处理
    - 如果未做适配，需要在 Biz 层做转换

#### 4.3.3 工作量

| 工作项 | 时间 |
|--------|------|
| pom.xml 依赖调整 | 0.5天 |
| 17个Biz文件注入替换 | 1天 |
| 166处调用点适配 | 2天 |
| Response 对象适配 | 1.5天 |
| 编译错误修复 | 1天 |
| 功能回归测试 | 2天 |
| **小计** | **8天** |

---

### 阶段四：lca_calculate-pro 背景数据库切换

#### 4.4.1 现有架构

lca_calculate-pro 直接操作数据库，已有动态表机制：

- `VersionConstant` - 版本常量
- `TableConstant` - 表名常量
- `InputTypeConstant` - 输入类型常量
- `DynamicTableNameParser` - MyBatis-Plus 动态表名解析器

涉及 Service：
- `service/basic/`：VersionService, UnitService, LocationsService, CategoriesService, ImpactMethodService, ImpactFactorService, ImpactCategoryService
- `service/mycat/`：GenerateProcessesService, GenerateProcessInputService, ProcessImpactAnalysisService

#### 4.4.2 切换方案

**方案 A：Feign 调用（推荐）**

将直接数据库操作改为 Feign 调用 ec-lcaadmin-pro。

- 优点：服务解耦，数据源统一
- 缺点：网络开销增加，需处理 Feign 超时和重试

**方案 B：数据源切换**

配置新数据源指向 ec-lcaadmin-pro 的数据库。

- 优点：无网络开销
- 缺点：服务耦合，动态表名需对齐

#### 4.4.3 工作量

| 工作项 | 时间 |
|--------|------|
| 分析现有直接数据库操作 | 0.5天 |
| 方案设计与评审 | 0.5天 |
| 实现切换逻辑 | 2天 |
| 动态表名对齐 | 1天 |
| LCA计算结果准确性验证 | 2天 |
| **小计** | **6天** |

---

### 阶段五：联调与集成测试

| 工作项 | 时间 |
|--------|------|
| 三服务联调 | 2天 |
| 性能测试 | 1天 |
| 数据一致性验证 | 2天 |
| Bug 修复 | 2天 |
| **小计** | **7天** |

---

## 五、时间预估汇总

| 阶段 | 工作内容 | 预估时间 |
|------|---------|---------|
| **阶段一** | ec-lcaadmin-pro 动态表改造 | **4天** |
| **阶段二** | ec-lcaadmin-pro 补全31个缺失接口（含字段映射） | **12.5天** |
| **阶段三** | manager-pro 替换 TransferProFeign（17文件，166处调用） | **8天** |
| **阶段四** | lca_calculate-pro 背景数据库切换 | **6天** |
| **阶段五** | 联调测试与 Bug 修复 | **7天** |
| **总计** | | **37.5天 ≈ 7.5周** |

### 建议排期：**38个工作日（约8周，2个月）**

---

## 六、分期实施建议

如果时间紧迫，建议分两期实施：

### 一期（4周）：核心功能跑通

| 工作内容 | 时间 |
|---------|------|
| 阶段一：ec-lcaadmin-pro 动态表改造 | 4天 |
| 阶段二（P0）：9个核心接口补全 | 3.5天 |
| 阶段二（P1）：9个重要接口补全 | 2.5天 |
| 阶段三：manager-pro 替换 | 8天 |
| 一期联调测试 | 3天 |
| **一期小计** | **21天（4.2周）** |

**一期目标**：manager-pro 的主要功能跑通，脱离 transfer-pro 依赖

### 二期（3.5周）：完整功能 + 计算引擎切换

| 工作内容 | 时间 |
|---------|------|
| 阶段二（P2）：13个辅助接口补全 | 2天 |
| 阶段四：lca_calculate-pro 切换 | 6天 |
| 二期联调测试 | 4天 |
| **二期小计** | **12天（2.4周）** |

**二期目标**：全面脱离 transfer-pro，lca_calculate-pro 切换到 ec-lcaadmin-pro

---

## 七、风险与缓解

### 🔴 致命风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 字段语义不完全对应 | 查询结果错误 | 在 Feign 层做完整的字段映射和类型转换 |
| LCA 计算精度问题 | 计算结果偏差 | 迁移前后同一套数据的计算结果对比测试 |
| 动态表名不一致 | 查询表不存在 | 统一动态表命名规则，增加表名校验 |

### 🟡 高风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Feign 调用性能 | 接口响应变慢 | 批量接口、缓存策略、异步调用 |
| 数据迁移丢失 | 历史数据不可用 | 数据迁移脚本 + 校验脚本 |
| 接口兼容性 | 调用方报错 | 先并行运行，灰度切换 |

### 🟢 一般风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 代码合并冲突 | 开发效率降低 | 按模块分批提交，减少并行开发 |
| 测试覆盖不足 | 线上问题 | 核心接口100%单元测试覆盖 |

---

## 八、附录

### A. ec-lcaadmin-pro 现有 Feign 接口

ec-lcaadmin-pro 已有 `ecdigit-lcaadmin-pro-feign` 模块，manager-pro 已依赖此模块。

### B. 动态表机制参考

lca_calculate-pro 的动态表实现：

- `VersionConstant` - 定义版本与表名后缀的映射
- `TableConstant` - 定义基础表名
- `DynamicTableNameParser` - MyBatis-Plus 拦截器，根据上下文动态替换表名
- `MybatisPlusConfig` - 注册拦截器

### C. TransferProFeign 完整接口列表

```java
// 基础数据接口
List<VersionResponse> getAllVersions();
VersionResponse getVersionById(Long id);
List<UnitResponse> getAllUnits(Long versionId);
UnitResponse getStandardUnitById(Long id, String groupUuid);
List<UnitResponse> getStandardUnitBatchByIds(List<Long> ids);
List<UnitResponse> getUnitBatchByIds(List<Long> ids);
UnitResponse getUnitById(Long id);
List<UnitGroupResponse> getUnitGroupList();
List<CategoriesResponse> getAllCategories(Long versionId);
List<CategoriesResponse> getCategoryList(Long versionId, String type);
List<CategoriesResponse> getCategoryTreeByProcess(Long versionId);
List<CategoriesResponse> getCategoriesListByUuIds(Long versionId, List<String> uuids);
List<LocationsResponse> getAllLocations();
LocationsResponse getLocationById(Long id);
LocationsTreeResponse getLocationsTree();

// 影响评价接口
List<ImpactMethodResponse> getImpactMethod();
List<ImpactCategoryResponse> getImpactCategory(Long versionId, List<String> ids);
List<ImpactCategoryResponse> getImpactCategoriesByMethodId(Long versionId, Long methodId);
List<ImpactMethodResponse> getMethodByFlows(Long versionId, List<String> flows);
List<UnitResponse> getLciUnits(Long versionId, LciUnitRequest req);

// 流接口
List<FlowsResponse> getFlowsByStandardIds(Long versionId, List<String> ids);
List<FlowsResponse> getFLows(Long versionId);
PageResult<FlowsResponse> getFLowList(Long versionId, FlowListRequest req);
List<MyCatFlowsResponse> getMyCatFlowsByIds(Long versionId, List<Long> ids);

// 工艺过程接口
List<ProcessesResponse> getProcessByStandardUuids(Long versionId, List<String> uuids);
List<MyCatProcessResponse> getMyCatProcessByIds(Long versionId, List<Long> ids);
MyCatProcessResponse getMyCatProcessById(Long versionId, Long id);
List<MyCatProcessResponse> getMyCatProcessByUuids(Long versionId, List<String> uuids);
PageResult<ProcessesResponse> queryProcessPageList(ProcessPageRequest req);
PageResult<ProcessInputResponse> getMyCatProcessInputPage(ProcessInputPageRequest req);

// 生成工艺过程接口
List<GenerateProcessesResponse> getGenerateProcessByUuids(Long versionId, List<String> uuids);
GenerateProcessesResponse addGenerateProcess(AddGenerateProcessRequest request);
GenerateProcessesResponse editGenerateProcess(EditGenerateProcessRequest request);
ProcessImpactAnalysisResponse generateProcessImpactAnalysis(String uuid);
List<ProcessImpactAnalysisResponse> getImpactAnalysisList(List<String> uuids);
GenerateProcessInputResponse getGenerateProcessInput(Long versionId, String processUuid);
```