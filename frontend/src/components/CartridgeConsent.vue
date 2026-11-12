<script setup lang="ts">
import { ref, watch } from 'vue'
import { cartridgeConsent, resolveCartridgeConsent } from '../accounts/cartridgeConsent'
import AdminDialog from './AdminDialog.vue'
const selected = ref<string[]>([])
watch(cartridgeConsent, () => {
  selected.value = []
})
</script>
<template>
  <AdminDialog
    :open="!!cartridgeConsent"
    :title="$t('cartridgeConsent.approveCartridgeUse')"
    @close="resolveCartridgeConsent(null)"
  >
    <template v-if="cartridgeConsent">
      <p class="alert warning">{{ cartridgeConsent.message }}</p>
      <div class="form-stack">
        <article v-for="item in cartridgeConsent.items" :key="item.copy_id" class="inset">
          <label class="checkbox"
            ><input v-model="selected" type="checkbox" :value="item.copy_id" />{{ item.requester }}
            {{ $t('common.copy') }} {{ item.ordinal }}</label
          >
          <img
            v-if="item.preview"
            :src="item.preview"
            :alt="$t('common.labelPreview')"
            class="consent-preview"
          />
          <p>
            {{ $t('cartridgeConsent.estimatedCostUpTo') }} {{ item.actual }} {{ item.currency }}
            {{ $t('common.chargeUpTo') }} {{ item.maximum_charge }} {{ item.currency }}
          </p>
        </article>
      </div>
      <button
        class="primary"
        :disabled="!selected.length"
        @click="resolveCartridgeConsent(selected)"
      >
        {{ $t('cartridgeConsent.approveSelectedCopies') }}
      </button>
    </template>
  </AdminDialog>
</template>
<style scoped>
.consent-preview {
  display: block;
  max-width: 100%;
  max-height: 120px;
  margin-block: 12px;
  object-fit: contain;
}
</style>
