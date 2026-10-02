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
import Settings from './views/Settings.vue'
import Fonts from './views/Fonts.vue'
import Images from './views/Images.vue'
import CsvRuns from './views/CsvRuns.vue'
import Templates from './views/Templates.vue'
import TemplateEditor from './views/TemplateEditor.vue'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/images',
      component: Images,
      meta: { title: 'Images', subtitle: 'Artwork for your labels.' },
    },
    {
      path: '/fonts',
      component: Fonts,
      meta: { title: 'Fonts', subtitle: 'Add typefaces for your labels.' },
    },
    {
      path: '/runs/:id?',
      component: CsvRuns,
      meta: {
        title: 'CSV runs',
        subtitle: 'Map your data, review every label, and queue a run.',
      },
    },
    {
      path: '/templates/new',
      component: TemplateEditor,
      meta: { title: 'New template', subtitle: 'Design a reusable label.' },
    },
    {
      path: '/templates/:id/edit',
      component: TemplateEditor,
      meta: {
        title: 'Template editor',
        subtitle: 'Arrange text, images, QR codes and shapes on your tape.',
      },
    },
    {
      path: '/',
      component: Dashboard,
      meta: { title: 'Overview', subtitle: 'A little order, one label at a time.' },
    },
    {
      path: '/queue',
      component: Jobs,
      meta: { title: 'Print queue', subtitle: 'Every label in its own time, on the right tape.' },
    },
    {
      path: '/new',
      component: NewLabel,
      meta: { title: 'New label', subtitle: 'Choose your tape and add a label to the queue.' },
    },
    {
      path: '/profiles',
      component: Profiles,
      meta: {
        title: 'Tape profiles',
        subtitle: 'Colors, widths, and a printing rhythm for each tape.',
      },
    },
    {
      path: '/cartridges',
      component: Cartridges,
      meta: { title: 'Cartridges', subtitle: 'Keep track of the tape you actually have.' },
    },
    {
      path: '/templates',
      component: Templates,
      meta: { title: 'Templates', subtitle: 'Reusable layouts for the things around you.' },
    },
    {
      path: '/activity',
      component: Activity,
      meta: { title: 'Activity', subtitle: 'Recent print attempts and notifications.' },
    },
    {
      path: '/batches/:id',
      component: Review,
      meta: { title: 'Batch details', subtitle: 'Check what printed before continuing.' },
    },
    {
      path: '/settings',
      component: Settings,
      meta: {
        title: 'Printer & settings',
        subtitle: 'Connection status and mock-printer controls.',
      },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.afterEach((to) => {
  document.title = `${String(to.meta.title)} · Label room`
})
createApp(App).use(router).mount('#app')
