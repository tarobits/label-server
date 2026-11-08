<script setup lang="ts">
import { ref, watch } from 'vue'
import { cartridgeConsent, resolveCartridgeConsent } from '../cartridgeConsent'
import AdminDialog from './AdminDialog.vue'
const selected = ref<string[]>([])
watch(cartridgeConsent, () => {
  selected.value = []
})
</script>
<template>
  <AdminDialog
    :open="!!cartridgeConsent"
    title="Approve cartridge use"
    @close="resolveCartridgeConsent(null)"
  >
    <template v-if="cartridgeConsent">
      <p class="alert warning">{{ cartridgeConsent.message }}</p>
      <div class="form-stack">
        <article v-for="item in cartridgeConsent.items" :key="item.copy_id" class="inset">
          <label class="checkbox"
            ><input v-model="selected" type="checkbox" :value="item.copy_id" />{{
              item.requester
            }}
            · Copy {{ item.ordinal }}</label
          >
          <img
            v-if="item.preview"
            :src="item.preview"
            alt="Label preview"
            class="consent-preview"
          />
          <p>
            Estimated cost up to {{ item.actual }} {{ item.currency }} · Charge up to
            {{ item.maximum_charge }} {{ item.currency }}
          </p>
        </article>
      </div>
      <button
        class="primary"
        :disabled="!selected.length"
        @click="resolveCartridgeConsent(selected)"
      >
        Approve selected copies
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
