<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

import { api, type UserAdmin } from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { describeError } from '@/copy'

const users = ref<UserAdmin[]>([])
const loading = ref(true)
const error = ref('')
const form = ref({
  email: '',
  display_name: '',
  role: 'expert' as UserAdmin['role'],
  is_synthetic: false,
})
const invite = ref<{ name: string; url: string } | null>(null)
const copied = ref('')
const editing = ref<{ id: string; name: string } | null>(null)
const toggling = ref<UserAdmin | null>(null)

function status(u: UserAdmin): string {
  if (!u.is_active) return 'Deactivated'
  return u.invite_pending ? 'Invite not accepted' : 'Active'
}

async function load() {
  try {
    const { data } = await api.GET('/api/v1/users')
    users.value = data ?? []
  } catch (e) {
    error.value = describeError(e)
  } finally {
    loading.value = false
  }
}

/** Runs a change, then shows the list again. */
async function act(call: () => Promise<void>) {
  error.value = ''
  try {
    await call()
  } catch (e) {
    error.value = describeError(e)
  }
  await load()
}

const showInvite = (name: string, path: string) => {
  invite.value = { name, url: location.origin + path }
  copied.value = ''
}

const add = () =>
  act(async () => {
    const { data } = await api.POST('/api/v1/users', { body: form.value })
    if (data) showInvite(data.user.display_name, data.invite_path)
    form.value = { ...form.value, email: '', display_name: '' }
  })

const reinvite = (u: UserAdmin) =>
  act(async () => {
    const { data } = await api.POST('/api/v1/users/{user_id}/invite', {
      params: { path: { user_id: u.id } },
    })
    if (data) showInvite(u.display_name, data.invite_path)
  })

const rename = () =>
  act(async () => {
    const e = editing.value
    editing.value = null
    if (e)
      await api.PATCH('/api/v1/users/{user_id}', {
        params: { path: { user_id: e.id } },
        body: { display_name: e.name },
      })
  })

const toggleActive = () =>
  act(async () => {
    const u = toggling.value
    toggling.value = null
    if (u)
      await api.PATCH('/api/v1/users/{user_id}', {
        params: { path: { user_id: u.id } },
        body: { is_active: !u.is_active },
      })
  })

async function copy() {
  try {
    await navigator.clipboard.writeText(invite.value?.url ?? '')
    copied.value = 'Copied.'
  } catch {
    copied.value = 'Could not copy. Select the link and copy it yourself.'
  }
}

// The link can't be fetched again, so leaving the page needs a second thought.
const warn = (event: BeforeUnloadEvent) => invite.value && event.preventDefault()
onBeforeRouteLeave(
  () => !invite.value || window.confirm("The invite link can't be shown again. Leave anyway?"),
)
onMounted(() => {
  void load()
  window.addEventListener('beforeunload', warn)
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', warn))
</script>

<template>
  <div>
    <h1>Experts</h1>
    <p v-if="error" class="alert mt-4" role="alert">{{ error }}</p>

    <div
      v-if="invite"
      class="mt-6 rounded-md border border-action p-4"
      role="status"
      data-testid="invite"
    >
      <p>
        Invite link for <strong>{{ invite.name }}</strong
        >. It can't be shown again, so send it now.
      </p>
      <input
        readonly
        :value="invite.url"
        class="field"
        aria-label="Invite link"
        @focus="($event.target as HTMLInputElement).select()"
      />
      <div class="mt-3 flex items-center gap-3">
        <button type="button" class="btn" @click="copy">Copy link</button>
        <button type="button" class="btn-quiet" @click="invite = null">I have sent it</button>
        <span v-if="copied" class="text-sm">{{ copied }}</span>
      </div>
    </div>

    <form
      class="mt-6 grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end"
      @submit.prevent="add"
    >
      <label class="text-sm"
        >Email<input v-model="form.email" type="email" required class="field"
      /></label>
      <label class="text-sm"
        >Name<input v-model="form.display_name" required class="field"
      /></label>
      <label class="text-sm"
        >Role
        <select v-model="form.role" class="field">
          <option value="expert">Expert</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      <button class="btn">Add account</button>
      <details class="text-sm sm:col-span-4">
        <summary class="cursor-pointer">Advanced</summary>
        <label class="mt-2 flex items-center gap-2"
          ><input v-model="form.is_synthetic" type="checkbox" /> Test account (synthetic)</label
        >
      </details>
    </form>

    <p v-if="loading" class="mt-6 text-muted">Loading…</p>
    <table v-else class="mt-8 w-full border-collapse text-left text-sm">
      <thead>
        <tr class="border-b border-line text-muted">
          <th
            v-for="h in ['Name', 'Email', 'Pseudonym', 'Role', 'Status', '']"
            :key="h"
            scope="col"
            class="py-2 pr-4 font-medium"
          >
            {{ h }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id" class="border-b border-line" data-testid="user">
          <td class="py-3 pr-4">
            <form v-if="editing?.id === u.id" class="flex gap-2" @submit.prevent="rename">
              <input
                v-model="editing.name"
                required
                class="field !mt-0"
                :aria-label="`Name of ${u.display_name}`"
              />
              <button class="btn">Save</button>
            </form>
            <template v-else>{{ u.display_name }}</template>
          </td>
          <td class="py-3 pr-4">{{ u.email }}</td>
          <td class="py-3 pr-4"><PseudonymChip :pseudonym="u.pseudonym" /></td>
          <td class="py-3 pr-4 capitalize">{{ u.role }}</td>
          <td class="py-3 pr-4" data-testid="status">{{ status(u) }}</td>
          <td class="space-x-2 py-3 text-right whitespace-nowrap">
            <button
              type="button"
              class="btn-quiet !px-3 !py-1"
              @click="editing = { id: u.id, name: u.display_name }"
            >
              Edit name
            </button>
            <button
              v-if="u.is_active"
              type="button"
              class="btn-quiet !px-3 !py-1"
              @click="reinvite(u)"
            >
              New invite link
            </button>
            <button type="button" class="btn-quiet !px-3 !py-1" @click="toggling = u">
              {{ u.is_active ? 'Deactivate' : 'Reactivate' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <ConfirmDialog
      v-if="toggling"
      :title="toggling.is_active ? 'Deactivate this account?' : 'Reactivate this account?'"
      :confirm-label="toggling.is_active ? 'Deactivate' : 'Reactivate'"
      cancel-label="Cancel"
      @confirm="toggleActive"
      @cancel="toggling = null"
    >
      <p v-if="toggling.is_active">
        {{ toggling.display_name }} will no longer be able to sign in.
      </p>
      <p v-else>{{ toggling.display_name }} will be able to sign in again.</p>
    </ConfirmDialog>
  </div>
</template>
