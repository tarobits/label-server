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
import './focusVisibility'
import { pinia } from './stores'
import { registerAppWorker } from './pwa'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/cartridge-quotes/:id',
      component: CartridgeQuote,
      meta: { title: 'Printing price approval' },
    },
    { path: '/companions', component: Companions, meta: { title: 'Companions' } },
    { path: '/resource-access', component: ResourceAccess, meta: { title: 'Locations & access' } },
    { path: '/migration', component: Migration, meta: { title: 'Ownership migration' } },
    { path: '/forgot-password', component: AccountRecovery, meta: { title: 'Forgot password' } },
    { path: '/reset-password', component: AccountRecovery, meta: { title: 'Reset password' } },
    { path: '/verify-email', component: AccountRecovery, meta: { title: 'Verify email' } },
    { path: '/usage', component: Usage, meta: { title: 'Tape usage' } },
    { path: '/account', component: AccountSettings, meta: { title: 'Account settings' } },
    {
      path: '/access-holds',
      component: AccessHolds,
      meta: {
        title: 'Paused labels',
      },
    },
    {
      path: '/admin',
      component: Administration,
      meta: {
        title: 'Administration',
      },
    },
    {
      path: '/requests/:id?',
      component: Requests,
      meta: {
        title: 'Print requests',
      },
    },
    {
      path: '/printers',
      component: Printers,
      meta: {
        title: 'Printers & groups',
      },
    },
    {
      path: '/images',
      component: Images,
      meta: { title: 'Images' },
    },
    {
      path: '/fonts',
      component: Fonts,
      meta: { title: 'Fonts' },
    },
    {
      path: '/runs/:id?',
      component: CsvRuns,
      meta: {
        title: 'CSV runs',
      },
    },
    {
      path: '/templates/new',
      component: TemplateEditor,
      meta: { title: 'New template' },
    },
    {
      path: '/templates/:id/edit',
      component: TemplateEditor,
      meta: {
        title: 'Template editor',
      },
    },
    {
      path: '/',
      component: Dashboard,
      meta: { title: 'Overview' },
    },
    {
      path: '/queue',
      component: Jobs,
      meta: { title: 'Print queue' },
    },
    {
      path: '/new',
      component: NewLabel,
      meta: { title: 'New label' },
    },
    {
      path: '/profiles',
      component: Profiles,
      meta: {
        title: 'Tape profiles',
      },
    },
    {
      path: '/cartridges',
      component: Cartridges,
      meta: { title: 'Cartridges' },
    },
    {
      path: '/templates',
      component: Templates,
      meta: { title: 'Templates' },
    },
    {
      path: '/activity',
      component: Activity,
      meta: { title: 'Print Activity' },
    },
    {
      path: '/audit',
      component: AuditLog,
      meta: { title: 'Audit log' },
    },
    { path: '/retries/:id', component: RetryOffer, meta: { title: 'Retry approval' } },
    {
      path: '/notification-history',
      component: DeliveryHistory,
      meta: { title: 'Notification delivery' },
    },
    {
      path: '/printer-changes',
      component: PrinterChangeHistory,
      meta: { title: 'Printer changes' },
    },
    {
      path: '/batches/:id/packing',
      component: Packing,
      meta: { title: 'Batch packing' },
    },
    {
      path: '/batches/:id',
      component: Review,
      meta: { title: 'Batch details' },
    },
    {
      path: '/settings',
      redirect: (to) => ({ path: '/printers', query: to.query }),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.afterEach((to) => {
  document.title = `${String(to.meta.title)} · Taro's Label Room`
})
createApp(App).use(pinia).use(router).mount('#app')

registerAppWorker()
