import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './views/Dashboard.vue'
import Jobs from './views/Jobs.vue'
import NewLabel from './views/NewLabel.vue'
import Profiles from './views/Profiles.vue'
import Cartridges from './views/Cartridges.vue'
import Activity from './views/Activity.vue'
import Packing from './views/Packing.vue'
import AuditLog from './views/AuditLog.vue'
import DeliveryHistory from './views/DeliveryHistory.vue'
import PrinterChangeHistory from './components/PrinterChangeHistory.vue'
import Usage from './views/Usage.vue'
import GroupAccounts from './views/GroupAccounts.vue'
import Review from './views/Review.vue'
import RetryOffer from './views/RetryOffer.vue'
import CartridgeQuote from './views/CartridgeQuote.vue'
import Fonts from './views/Fonts.vue'
import Images from './views/Images.vue'
import Printers from './views/Printers.vue'
import CsvRuns from './views/CsvRuns.vue'
import Templates from './views/Templates.vue'
import TemplateEditor from './views/TemplateEditor.vue'
import Administration from './views/Administration.vue'
import ResourceAccess from './views/ResourceAccess.vue'
import Companions from './views/Companions.vue'
import Migration from './views/Migration.vue'
import Requests from './views/Requests.vue'
import AccessHolds from './views/AccessHolds.vue'
import AccountSettings from './views/AccountSettings.vue'
import AccountRecovery from './views/AccountRecovery.vue'
import './style.css'
import './motion.css'
import './shared/focusVisibility'
import { pinia } from './stores'
import { registerAppWorker } from './shared/pwa'
import { i18n, locale, t } from './shared/i18n'
import { watch } from 'vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/cartridge-quotes/:id',
      component: CartridgeQuote,
      meta: { title: 'common.printingPriceApproval' },
    },
    { path: '/companions', component: Companions, meta: { title: 'companions.companions' } },
    {
      path: '/resource-access',
      component: ResourceAccess,
      meta: { title: 'common.locationsAccess' },
    },
    { path: '/migration', component: Migration, meta: { title: 'common.ownershipMigration' } },
    {
      path: '/forgot-password',
      component: AccountRecovery,
      meta: { title: 'common.forgotPassword' },
    },
    {
      path: '/reset-password',
      component: AccountRecovery,
      meta: { title: 'common.resetPassword' },
    },
    { path: '/verify-email', component: AccountRecovery, meta: { title: 'common.verifyEmail' } },
    { path: '/usage', component: Usage, meta: { title: 'common.tapeUsage' } },
    { path: '/group-accounts', component: GroupAccounts, meta: { title: 'common.groupAccounts' } },
    { path: '/account', component: AccountSettings, meta: { title: 'navigation.account' } },
    {
      path: '/access-holds',
      component: AccessHolds,
      meta: {
        title: 'common.pausedLabels',
      },
    },
    {
      path: '/admin',
      component: Administration,
      meta: {
        title: 'common.administration',
      },
    },
    {
      path: '/requests/:id?',
      component: Requests,
      meta: {
        title: 'common.printRequests',
      },
    },
    {
      path: '/printers',
      component: Printers,
      meta: {
        title: 'common.printersGroups',
      },
    },
    {
      path: '/images',
      component: Images,
      meta: { title: 'common.images' },
    },
    {
      path: '/fonts',
      component: Fonts,
      meta: { title: 'common.fonts' },
    },
    {
      path: '/runs/:id?',
      component: CsvRuns,
      meta: {
        title: 'common.csvRuns',
      },
    },
    {
      path: '/templates/new',
      component: TemplateEditor,
      meta: { title: 'common.newTemplate' },
    },
    {
      path: '/templates/:id/edit',
      component: TemplateEditor,
      meta: {
        title: 'common.templateEditor',
      },
    },
    {
      path: '/',
      component: Dashboard,
      meta: { title: 'common.overview' },
    },
    {
      path: '/queue',
      component: Jobs,
      meta: { title: 'common.printQueue' },
    },
    {
      path: '/new',
      component: NewLabel,
      meta: { title: 'app.newLabel' },
    },
    {
      path: '/profiles',
      component: Profiles,
      meta: {
        title: 'common.tapeProfiles',
      },
    },
    {
      path: '/cartridges',
      component: Cartridges,
      meta: { title: 'resourceAccess.cartridges' },
    },
    {
      path: '/templates',
      component: Templates,
      meta: { title: 'common.templates' },
    },
    {
      path: '/activity',
      component: Activity,
      meta: { title: 'common.printActivity' },
    },
    {
      path: '/audit',
      component: AuditLog,
      meta: { title: 'common.auditLog' },
    },
    { path: '/retries/:id', component: RetryOffer, meta: { title: 'retryOffer.retryApproval' } },
    {
      path: '/notification-history',
      component: DeliveryHistory,
      meta: { title: 'common.notificationDelivery' },
    },
    {
      path: '/printer-changes',
      component: PrinterChangeHistory,
      meta: { title: 'common.printerChanges' },
    },
    {
      path: '/batches/:id/packing',
      component: Packing,
      meta: { title: 'companionPacking.batchPacking' },
    },
    {
      path: '/batches/:id',
      component: Review,
      meta: { title: 'packing.batchDetails' },
    },
    {
      path: '/settings',
      redirect: (to) => ({ path: '/printers', query: to.query }),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.afterEach((to) => {
  document.title = `${t(String(to.meta.title))} · Taro's Label Room`
})
watch(locale, () => {
  document.title = `${t(String(router.currentRoute.value.meta.title ?? 'common.overview'))} · Taro's Label Room`
})
createApp(App).use(pinia).use(router).use(i18n).mount('#app')

registerAppWorker()
