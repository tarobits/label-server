import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './views/Dashboard.vue'
import Jobs from './views/Jobs.vue'
import NewLabel from './views/NewLabel.vue'
import Profiles from './views/Profiles.vue'
import Cartridges from './views/Cartridges.vue'
import Activity from './views/Activity.vue'
import Review from './views/Review.vue'
import Fonts from './views/Fonts.vue'
import Images from './views/Images.vue'
import Printers from './views/Printers.vue'
import CsvRuns from './views/CsvRuns.vue'
import Templates from './views/Templates.vue'
import TemplateEditor from './views/TemplateEditor.vue'
import Administration from './views/Administration.vue'
import Requests from './views/Requests.vue'
import AccessHolds from './views/AccessHolds.vue'
import './style.css'
import './motion.css'
import { pinia } from './stores'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
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
      meta: { title: 'Activity' },
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
