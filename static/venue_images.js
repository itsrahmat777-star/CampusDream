// Maps event id keywords → deterministic Unsplash image
// Uses picsum.photos as fallback (no API key, reliable)
window.VENUE_IMAGES = {
  keywords: {
    'cbit': 'https://images.unsplash.com/photo-1562774053-701939374585?w=600&q=80',
    'osmania': 'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?w=600&q=80',
    'jntuh': 'https://images.unsplash.com/photo-1580582932707-520aed937b7b?w=600&q=80',
    'mgit': 'https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?w=600&q=80',
    'vnr': 'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?w=600&q=80',
    'vasavi': 'https://images.unsplash.com/photo-1498243691581-b145c3f54a5a?w=600&q=80',
    'cvr': 'https://images.unsplash.com/photo-1607237138185-eedd9c632b0b?w=600&q=80',
    't-hub': 'https://images.unsplash.com/photo-1497366216548-37526070297c?w=600&q=80',
    'ravindra': 'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=600&q=80',
    'sports': 'https://images.unsplash.com/photo-1540747913346-19e32dc3e97e?w=600&q=80',
    'auditorium': 'https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=600&q=80',
    'seminar': 'https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=600&q=80',
    'lab': 'https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?w=600&q=80',
    'ground': 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=600&q=80',
  },
  // category fallbacks
  category: {
    'technical': 'https://images.unsplash.com/photo-1517048676732-d65bc937f952?w=600&q=80',
    'cultural':  'https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=600&q=80',
    'sports':    'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=600&q=80',
    'arts':      'https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=600&q=80',
    'general':   'https://images.unsplash.com/photo-1531058020387-3be344556be6?w=600&q=80',
  },
  getUrl: function(venue, category) {
    var v = (venue || '').toLowerCase();
    var keys = Object.keys(this.keywords);
    for (var i = 0; i < keys.length; i++) {
      if (v.indexOf(keys[i]) !== -1) return this.keywords[keys[i]];
    }
    return this.category[(category||'general').toLowerCase()] || this.category['general'];
  }
};
