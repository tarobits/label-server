<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { api, ApiError, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import type { AssetSharing } from '../types'
import AssetScopeFields from './AssetScopeFields.vue'

const props = defineProps<{ kind: 'images' | 'fonts' }>()
const auth = useAuthStore(),
  w = useWorkspaceStore()
const singular = computed(() => (props.kind === 'images' ? 'image' : 'font'))
const sharing = ref<AssetSharing>({ scope: 'personal', group_id: null })
const files = ref<
  { file: File; state: 'Ready' | 'Uploading' | 'Uploaded' | 'Failed'; error: string }[]
>([])
const uploading = ref(false),
  error = ref('')
const cancelled = ref(false)
const remaining = computed(() => files.value.filter((item) => item.state !== 'Uploaded'))
const allowed = computed(() =>
  sharing.value.scope === 'group'
    ? !!sharing.value.group_id &&
      (auth.user?.is_admin ||
        auth.user?.group_memberships[sharing.value.group_id]?.[props.kind]?.can_create)
    : auth.can(`${props.kind}.create_${sharing.value.scope}`),
)
function choose(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files ?? []).map((file) => ({
    file,
    state: 'Ready',
    error: '',
  }))
  error.value = ''
}
async function upload() {
  if (uploading.value || !allowed.value) return
  uploading.value = true
  cancelled.value = false
  error.value = ''
  const actor = auth.user?.id,
    target = { ...sharing.value }
  for (const item of remaining.value) {
    if (cancelled.value || auth.user?.id !== actor) break
    item.state = 'Uploading'
    item.error = ''
    try {
      if (item.file.size > 5_000_000) throw new Error(`Upload a ${singular.value} of at most 5 MB.`)
      const query = new URLSearchParams({ scope: target.scope, name: item.file.name })
      if (target.group_id) query.set('group_id', target.group_id)
      await api(`/${singular.value}-assets?${query}`, 'POST', item.file)
      item.state = 'Uploaded'
    } catch (cause) {
      item.state = 'Failed'
      item.error = errorMessage(cause)
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) cancelled.value = true
    }
  }
  try {
    await w.refresh()
  } catch (cause) {
    error.value = errorMessage(cause)
  }
  uploading.value = false
}
onUnmounted(() => {
  cancelled.value = true
})
</script>
<template>
  <section v-if="auth.canUpload(kind)" class="panel form-stack">
    <h2>Upload {{ kind }}</h2>
    <p v-if="kind === 'fonts'" class="help">
      Static TTF and OTF files, up to 5 MB each. Variable fonts, font collections and color fonts
      are not supported.
    </p>
    <template v-else>
      <p class="help">
        PNG, JPEG, WebP, BMP, still GIF or simple SVG, up to 5 MB each. Bitmaps are limited to 16
        megapixels and 8192 pixels per side.
      </p>
      <p class="help">
        SVG supports paths and basic shapes. Convert text to paths and remove styles, embedded
        images, filters and external references before uploading.
      </p>
    </template>
    <AssetScopeFields v-model="sharing" :kind="kind" :disabled="uploading" />
    <label
      >{{ kind === 'fonts' ? 'Font files' : 'Image files'
      }}<input
        type="file"
        multiple
        :accept="kind === 'fonts' ? '.ttf,.otf' : '.png,.jpg,.jpeg,.webp,.bmp,.gif,.svg'"
        :disabled="uploading"
        @change="choose"
    /></label>
    <Transition name="panel-expand">
      <ul v-if="files.length" class="upload-results" aria-live="polite" aria-label="Upload results">
        <li v-for="(item, index) in files" :key="index" class="list-row">
          <div class="grow">
            <strong>{{ item.file.name }}</strong
            ><small v-if="item.error" class="danger-text">{{ item.error }}</small>
          </div>
          <span>{{ item.state }}</span>
        </li>
      </ul>
    </Transition>
    <div class="row wrap">
      <button
        class="primary"
        :disabled="uploading || !remaining.length || !allowed"
        @click="upload"
      >
        {{
          uploading
            ? 'Uploading…'
            : remaining.length && remaining.every((item) => item.state === 'Failed')
              ? 'Retry failed uploads'
              : `Upload ${singular}${files.length > 1 ? 's' : ''}`
        }}
      </button>
      <Transition name="notice">
        <button
          v-if="uploading"
          class="secondary motion-reveal"
          :disabled="cancelled"
          @click="cancelled = true"
        >
          Cancel remaining
        </button>
      </Transition>
    </div>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
  </section>
</template>
<style scoped>
.upload-results {
  list-style: none;
  padding: 0;
  margin: 0;
}
.upload-results .grow {
  min-width: 0;
  overflow-wrap: anywhere;
}
.upload-results li > span {
  flex-shrink: 0;
  font-size: 13px;
}
</style>
