<script setup lang="ts">
import type { Data, Evidence } from '../types.ts'
import { label, toolLabels } from '../presentation.ts'
defineProps<{ evidence: Evidence }>()
const rows = (data: unknown): Data[] => Array.isArray(data) ? data : data && typeof data === 'object' ? [data as Data] : []
const specs = (data: unknown) => data && typeof data === 'object' ? Object.values(data).join(' / ') : ''
const time = (value: unknown) => value ? new Date(String(value)).toLocaleString('zh-CN', { hour12: false }) : '未提供'
</script>

<template>
  <section class="evidence-card">
    <div class="eyebrow">资料 [{{ evidence.id }}] · {{ toolLabels[evidence.result.source] || '工具结果' }}</div>
    <p v-if="evidence.result.status !== 'success'" class="error-text">{{ label(evidence.result.status) }}，无法确认对应业务信息。</p>
    <template v-else>
      <article v-for="(data, index) in rows(evidence.result.data)" :key="index" class="business-record">
        <template v-if="['search_products', 'get_product'].includes(evidence.result.source)">
          <h3>{{ data.name }}</h3><p class="muted">{{ data.brand }} · {{ data.product_code }}</p>
          <p v-if="data.description">{{ data.description }}</p>
        </template>
        <template v-else-if="evidence.result.source === 'list_product_skus'">
          <h3>{{ specs(data.specs) }}</h3><p>{{ data.price }} {{ data.currency }}</p>
          <p class="muted">{{ data.sku_code }}</p>
        </template>
        <template v-else-if="evidence.result.source === 'get_inventory'">
          <p v-if="!rows(data.stocks).length">暂无库存记录，可售数量未知。</p>
          <div v-for="(stock, i) in rows(data.stocks)" :key="i">
            <h3>可售库存 <strong class="stock-number">{{ stock.available }}</strong></h3>
            <p>{{ stock.warehouse_code }} · 在库 {{ stock.on_hand }} · 预留 {{ stock.reserved }}</p>
            <p class="muted">更新于 {{ time(stock.updated_at) }}</p>
          </div>
          <p class="note">查询结果不代表已为你锁定库存。</p>
        </template>
        <template v-else-if="evidence.result.source === 'get_order'">
          <h3>{{ data.order_no }}</h3><p><span class="badge">{{ label(data.status) }}</span> {{ label(data.payment_status) }}</p>
          <dl><dt>应付金额</dt><dd>{{ data.payable_amount }} {{ data.currency }}</dd><dt>已付金额</dt><dd>{{ data.paid_amount }} {{ data.currency }}</dd></dl>
          <div v-for="(item, i) in rows(data.items)" :key="i" class="order-item">
            <strong>{{ item.product_name_snapshot }}</strong><p>{{ specs(item.specs_snapshot) }} × {{ item.quantity }}</p>
            <p>明细金额 {{ item.line_amount }} {{ data.currency }}</p>
            <details><summary>退款申请所需明细编号</summary><code>{{ item.id }}</code></details>
          </div>
        </template>
        <template v-else-if="evidence.result.source === 'get_logistics'">
          <p v-if="!rows(data.packages).length">暂无包裹信息，不表示已送达。</p>
          <div v-for="(parcel, i) in rows(data.packages)" :key="i" class="order-item">
            <h3>{{ label(parcel.status) }}</h3><p>{{ parcel.latest_event || '暂无最新物流事件' }}</p>
            <p>{{ parcel.carrier_code || '承运商未提供' }} · {{ parcel.tracking_no || '单号未提供' }}</p>
            <p class="muted">同步于 {{ time(parcel.synced_at) }}</p>
          </div>
        </template>
        <template v-else-if="evidence.result.source === 'search_after_sales_policy'">
          <h3>{{ data.title }} <span class="badge">v{{ data.version }}</span></h3>
          <blockquote>{{ data.content }}</blockquote>
          <p class="muted locator">{{ data.locator }}</p><p class="note">{{ data.citation }}</p>
          <p class="note">来源原文不代表退款批准；历史订单的适用政策仍需核实。</p>
        </template>
        <p v-else>工具已返回资料，当前视图尚不支持该类型。</p>
      </article>
    </template>
    <footer class="muted">查询于 {{ time(evidence.result.queried_at) }}</footer>
  </section>
</template>
