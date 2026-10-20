document.addEventListener('alpine:init', () => {
  const NL = { latMin: 50.7, latMax: 53.7, lonMin: 3.2, lonMax: 7.3 };
  const MAX_PHOTO_BYTES = 15 * 1024 * 1024;
  const PAGE_SIZE = 12;
  const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers';
  const GENERIC_ERROR = 'Er ging iets mis. Probeer het straks nog eens.';
  const PIN_SVG =
    '<svg viewBox="0 0 32 42" width="40" height="52" aria-hidden="true" focusable="false">' +
    '<path d="M16 1C7.7 1 1 7.6 1 15.8 1 26.6 16 41 16 41s15-14.4 15-25.2C31 7.6 24.3 1 16 1z"/>' +
    '<circle cx="16" cy="15.5" r="6"/></svg>';

  const inNetherlands = (lat, lon) =>
    lat >= NL.latMin && lat <= NL.latMax && lon >= NL.lonMin && lon <= NL.lonMax;

  const pinIcon = (extraClass) =>
    L.divIcon({
      className: 'pin ' + extraClass,
      html: PIN_SVG,
      iconSize: [44, 52],
      iconAnchor: [22, 52],
      popupAnchor: [0, -48],
    });

  const clusterIcon = (cluster) =>
    L.divIcon({
      className: 'cluster',
      html: '<span>' + Number(cluster.getChildCount()) + '</span>',
      iconSize: [48, 48],
    });

  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  const errorDetail = async (response) => {
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') return body.detail;
    } catch (_) {
      /* geen JSON */
    }
    return GENERIC_ERROR;
  };

  const getJson = async (url) => {
    let response;
    try {
      response = await fetch(url, { headers: { Accept: 'application/json' } });
    } catch (_) {
      throw new Error('Geen verbinding. Controleer je internet en probeer het opnieuw.');
    }
    if (!response.ok) throw new Error(await errorDetail(response));
    return response.json();
  };

  const tileLayer = () =>
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION });

  const wheelOnFocus = (map) => {
    map.scrollWheelZoom.disable();
    map.on('focus', () => map.scrollWheelZoom.enable());
    map.on('blur', () => map.scrollWheelZoom.disable());
  };

  Alpine.data('bollen', () => {
    // Leaflet-objecten blijven buiten de reactieve state van Alpine.
    let self;
    let mainMap = null;
    let cluster = null;
    let pickMap = null;
    let pickMarker = null;
    let lastFocus = null;
    let fittedToMarkers = false;
    const markers = new Map();
    const detailCache = new Map();
    const nlViewBounds = () => L.latLngBounds([50.75, 3.35], [53.55, 7.25]);
    const nlMaxBounds = () => L.latLngBounds([50.2, 2.4], [54.2, 8.2]);

    const buildPopup = (post, popup) => {
      const card = element('div', 'popup-card');
      const photoButton = element('button', 'popup-photo');
      photoButton.type = 'button';
      photoButton.setAttribute('aria-label', 'Bekijk de foto van ' + post.name + ' groter');
      const img = element('img');
      img.alt = 'Foto van ' + post.name;
      img.addEventListener('load', () => popup.update());
      img.src = post.thumb_url;
      photoButton.appendChild(img);
      photoButton.addEventListener('click', () => self.openLightbox(post));
      card.appendChild(photoButton);
      card.appendChild(element('h3', 'popup-name', post.name));
      card.appendChild(element('p', 'popup-date', self.formatDate(post.created_at)));
      if (post.message) card.appendChild(element('p', 'popup-text', post.message));
      return card;
    };

    const fillPopup = async (marker, id) => {
      const popup = marker.getPopup();
      const cached = detailCache.get(id);
      if (!cached) popup.setContent(element('p', 'popup-status', 'Even laden…'));
      try {
        const post = await getJson('/api/posts/' + id);
        detailCache.set(id, post);
        popup.setContent(buildPopup(post, popup));
      } catch (error) {
        popup.setContent(
          cached
            ? buildPopup(cached, popup)
            : element('p', 'popup-status', 'Deze foto kon niet geladen worden.'),
        );
      }
    };

    const makeMarker = (p) => {
      const marker = L.marker([p.lat, p.lon], {
        icon: pinIcon('pin-post'),
        title: p.name,
        alt: 'Foto van ' + p.name,
      });
      marker.bindPopup(
        L.popup({ maxWidth: 300, minWidth: 240, autoPanPadding: [16, 16], className: 'bol-popup' }),
      );
      marker.on('popupopen', () => fillPopup(marker, p.id));
      return marker;
    };

    const addMarkers = (items) => {
      const fresh = [];
      for (const p of items) {
        if (markers.has(p.id)) continue;
        const marker = makeMarker(p);
        markers.set(p.id, marker);
        fresh.push(marker);
      }
      if (cluster && fresh.length) cluster.addLayers(fresh);
    };

    const fitToMarkers = () => {
      if (!mainMap || markers.size === 0) return;
      const points = Array.from(markers.values(), (m) => m.getLatLng());
      mainMap.invalidateSize();
      mainMap.fitBounds(L.latLngBounds(points), { padding: [32, 32], maxZoom: 12 });
      fittedToMarkers = true;
    };

    return {
      form: { name: '', message: '', website: '' },
      file: null,
      previewUrl: '',
      previewFailed: false,
      loc: null,
      geoBusy: false,
      locMessage: '',
      locMessageKind: '',
      errors: {},
      submitError: '',
      submitting: false,
      progress: 0,
      success: null,
      formOpen: false,

      posts: [],
      nextBeforeId: null,
      postsLoading: false,
      postsLoaded: false,
      postsError: '',
      mapCount: 0,
      mapLoaded: false,
      mapError: '',
      lightbox: null,

      init() {
        self = this;
        const syncScrollLock = () =>
          document.body.classList.toggle('no-scroll', Boolean(this.lightbox || this.formOpen));
        this.$watch('lightbox', (value) => {
          syncScrollLock();
          if (value) this.$nextTick(() => this.$refs.lightboxClose.focus());
        });
        this.$watch('formOpen', syncScrollLock);
        this.$nextTick(() => {
          this.initMainMap();
          this.loadMap();
          this.loadPosts();
          if (location.hash === '#delen') this.openForm();
        });
      },

      get hasErrors() {
        return Object.keys(this.errors).length > 0;
      },

      formatDate(iso) {
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleDateString('nl-NL', { day: 'numeric', month: 'long', year: 'numeric' });
      },

      // ---- Formulier-popup ----
      openForm() {
        if (this.formOpen) return;
        this.success = null;
        this.lightbox = null;
        if (document.activeElement && document.activeElement !== document.body)
          lastFocus = document.activeElement;
        this.formOpen = true;
        // De kies-kaart kan pas goed meten als de popup zichtbaar is.
        this.$nextTick(() => {
          const firstTime = !pickMap;
          if (firstTime) this.initPickMap();
          pickMap.invalidateSize();
          if (firstTime || !this.loc) pickMap.fitBounds(nlViewBounds());
          this.$refs.dialog.parentElement.scrollTop = 0;
          this.$refs.dialogTitle.focus({ preventScroll: true });
          // Na de eerste layout nog een keer meten, voor mobiele browsers die de popup laat uitrollen.
          setTimeout(() => pickMap && pickMap.invalidateSize(), 150);
        });
      },

      closeForm() {
        // Tijdens het versturen blijft de popup open, zodat een foutmelding of succes niet gemist wordt.
        if (!this.formOpen || this.submitting) return;
        this.formOpen = false;
        if (location.hash === '#delen')
          history.replaceState(null, '', location.pathname + location.search);
        const back = lastFocus && document.contains(lastFocus) ? lastFocus : this.$refs.opener;
        lastFocus = null;
        this.$nextTick(() => back.focus({ preventScroll: true }));
      },

      onEscape() {
        if (this.lightbox) this.closeLightbox();
        else this.closeForm();
      },

      trapTab(event) {
        const items = Array.from(
          this.$refs.dialog.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]), [tabindex="0"]',
          ),
        ).filter((el) => el.offsetParent !== null);
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (event.shiftKey && (active === first || !this.$refs.dialog.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || !this.$refs.dialog.contains(active))) {
          event.preventDefault();
          first.focus();
        }
      },

      // ---- Kaart: plek kiezen ----
      initPickMap() {
        pickMap = L.map(this.$refs.pickMap, {
          maxBounds: nlMaxBounds(),
          maxBoundsViscosity: 1,
          zoomSnap: 0.25,
        });
        tileLayer().addTo(pickMap);
        pickMap.fitBounds(nlViewBounds());
        pickMap.setMinZoom(pickMap.getBoundsZoom(nlMaxBounds()));
        wheelOnFocus(pickMap);
        pickMap.on('click', (event) => {
          this.locMessage = '';
          if (!this.setLocation(event.latlng.lat, event.latlng.lng, 'kaart')) {
            this.locMessage = 'Die plek ligt niet in Nederland. Tik een plek in Nederland aan.';
            this.locMessageKind = 'is-error';
          }
        });
      },

      setLocation(lat, lon, source) {
        if (!inNetherlands(lat, lon)) return false;
        this.loc = { lat, lon, source };
        delete this.errors.loc;
        if (pickMarker) {
          pickMarker.setLatLng([lat, lon]);
        } else {
          pickMarker = L.marker([lat, lon], {
            draggable: true,
            icon: pinIcon('pin-pick'),
            title: 'Jouw plek – sleep om te verplaatsen',
          }).addTo(pickMap);
          pickMarker.on('dragend', () => {
            const at = pickMarker.getLatLng();
            if (!this.setLocation(at.lat, at.lng, 'kaart')) {
              pickMarker.setLatLng([this.loc.lat, this.loc.lon]);
              this.locMessage = 'Die plek ligt niet in Nederland. De speld is teruggezet.';
              this.locMessageKind = 'is-error';
            }
          });
        }
        return true;
      },

      useLocation() {
        this.locMessage = '';
        if (!navigator.geolocation) {
          this.locMessage =
            'Je toestel kan je locatie niet doorgeven. Tik hieronder op de kaart op de plek van je bol.';
          this.locMessageKind = 'is-error';
          return;
        }
        this.geoBusy = true;
        navigator.geolocation.getCurrentPosition(
          (position) => {
            this.geoBusy = false;
            const { latitude, longitude } = position.coords;
            if (!this.setLocation(latitude, longitude, 'gps')) {
              this.locMessage =
                'Je locatie ligt buiten Nederland. Tik hieronder op de kaart de plek van je bol aan.';
              this.locMessageKind = 'is-error';
              return;
            }
            pickMap.setView([latitude, longitude], Math.max(pickMap.getZoom(), 12));
            this.locMessage =
              'Gelukt! Klopt de plek niet helemaal? Versleep dan de speld op de kaart.';
            this.locMessageKind = 'is-ok';
          },
          (error) => {
            this.geoBusy = false;
            const tail = ' Dat is niet erg: tik hieronder op de kaart op de plek van je bol.';
            if (error.code === 1) {
              this.locMessage =
                'Je hebt niet toegestaan dat deze website je locatie gebruikt.' + tail;
            } else if (error.code === 3) {
              this.locMessage = 'Het duurde te lang om je locatie te vinden.' + tail;
            } else {
              this.locMessage = 'We kunnen je locatie nu niet bepalen.' + tail;
            }
            this.locMessageKind = 'is-error';
          },
          { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 },
        );
      },

      // ---- Formulier ----
      onFile(event) {
        const chosen = event.target.files && event.target.files[0];
        this.clearPreview();
        delete this.errors.photo;
        if (!chosen) {
          this.file = null;
          return;
        }
        this.file = chosen;
        this.previewFailed = false;
        this.previewUrl = URL.createObjectURL(chosen);
        if (chosen.size > MAX_PHOTO_BYTES) {
          this.errors.photo = 'Deze foto is te groot. Kies een foto van maximaal 15 MB.';
        }
      },

      clearPreview() {
        if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
        this.previewUrl = '';
        this.previewFailed = false;
      },

      validate() {
        const errors = {};
        if (!this.form.name.trim()) errors.name = 'Vul je naam in.';
        if (!this.file) errors.photo = 'Kies of maak een foto.';
        else if (this.file.type && !this.file.type.startsWith('image/'))
          errors.photo = 'Dit is geen foto. Kies een foto uit je galerij of maak er een.';
        else if (this.file.size > MAX_PHOTO_BYTES)
          errors.photo = 'Deze foto is te groot. Kies een foto van maximaal 15 MB.';
        if (!this.loc)
          errors.loc = 'Kies de plek van je bol: gebruik je locatie of tik op de kaart.';
        this.errors = errors;
        return Object.keys(errors).length === 0;
      },

      submit() {
        if (this.submitting) return;
        this.submitError = '';
        if (!this.validate()) {
          const first = this.errors.name ? 'name' : this.errors.photo ? 'photo' : 'pickMap';
          const target = this.$refs[first];
          if (target) target.scrollIntoView({ block: 'center' });
          if (first === 'name') target.focus({ preventScroll: true });
          return;
        }

        const body = new FormData();
        body.append('name', this.form.name.trim());
        body.append('message', this.form.message.replace(/\s*[\r\n]+\s*/g, ' ').trim());
        body.append('lat', this.loc.lat.toFixed(6));
        body.append('lon', this.loc.lon.toFixed(6));
        body.append('photo', this.file);
        body.append('website', this.form.website);

        this.submitting = true;
        this.progress = 0;
        const request = new XMLHttpRequest();
        request.open('POST', '/api/posts');
        request.timeout = 180000;
        request.responseType = 'text';
        request.setRequestHeader('Accept', 'application/json');
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) this.progress = Math.round((event.loaded / event.total) * 100);
        };
        request.onerror = () => this.failSubmit('Geen verbinding. Controleer je internet en probeer het opnieuw.');
        request.ontimeout = () => this.failSubmit('Het versturen duurt te lang. Probeer het opnieuw.');
        request.onload = () => {
          let data = null;
          try {
            data = JSON.parse(request.responseText);
          } catch (_) {
            /* lege of niet-JSON-body */
          }
          if (request.status === 201) {
            this.finishSubmit(data && typeof data.id === 'number' ? data : null);
          } else if (data && typeof data.detail === 'string') {
            this.failSubmit(data.detail);
          } else if (request.status === 413) {
            this.failSubmit('De foto is te groot. Kies een foto van maximaal 15 MB.');
          } else {
            this.failSubmit(GENERIC_ERROR);
          }
        };
        request.send(body);
      },

      failSubmit(message) {
        this.submitting = false;
        this.submitError = message;
        this.$nextTick(() => this.$refs.submitError.scrollIntoView({ block: 'center' }));
      },

      finishSubmit(post) {
        this.submitting = false;
        this.success = { name: this.form.name.trim(), post };
        if (post) {
          detailCache.set(post.id, post);
          addMarkers([post]);
          this.mapCount = markers.size;
          this.posts = [post, ...this.posts.filter((p) => p.id !== post.id)];
        }
        this.resetForm();
        this.closeForm();
        this.loadMap();
        if (post) this.$nextTick(() => this.focusOnMap(post.id));
      },

      resetForm() {
        this.form = { name: '', message: '', website: '' };
        this.file = null;
        this.$refs.photo.value = '';
        this.clearPreview();
        this.errors = {};
        this.loc = null;
        this.locMessage = '';
        this.submitError = '';
        if (pickMarker) {
          pickMarker.remove();
          pickMarker = null;
        }
      },

      // ---- Hoofdkaart ----
      initMainMap() {
        mainMap = L.map(this.$refs.mainMap, {
          maxBounds: nlMaxBounds(),
          maxBoundsViscosity: 1,
          zoomSnap: 0.25,
        });
        tileLayer().addTo(mainMap);
        mainMap.fitBounds(nlViewBounds());
        // markercluster tekent bij addLayers niets als minZoom een fractie is.
        mainMap.setMinZoom(Math.floor(mainMap.getBoundsZoom(nlMaxBounds())));
        wheelOnFocus(mainMap);
        cluster = L.markerClusterGroup({
          showCoverageOnHover: false,
          maxClusterRadius: 50,
          iconCreateFunction: clusterIcon,
        });
        mainMap.addLayer(cluster);
      },

      async loadMap() {
        this.mapError = '';
        try {
          const items = await getJson('/api/posts/map');
          addMarkers(items);
          this.mapCount = markers.size;
          this.mapLoaded = true;
          if (!fittedToMarkers) fitToMarkers();
        } catch (error) {
          this.mapError = 'De kaart kon de foto’s niet laden. ' + error.message;
        }
      },

      focusOnMap(id) {
        const post = detailCache.get(id) || this.posts.find((p) => p.id === id);
        if (!markers.has(id) && post) {
          addMarkers([post]);
          this.mapCount = markers.size;
        }
        this.lightbox = null;
        document.getElementById('kaart').scrollIntoView();
        const marker = markers.get(id);
        if (!marker) return;
        setTimeout(() => {
          mainMap.invalidateSize();
          cluster.zoomToShowLayer(marker, () => {
            mainMap.setView(marker.getLatLng(), Math.max(mainMap.getZoom(), 12));
            marker.openPopup();
          });
        }, 350);
      },

      // ---- Galerij ----
      async loadPosts() {
        if (this.postsLoading) return;
        this.postsLoading = true;
        this.postsError = '';
        try {
          let url = '/api/posts?limit=' + PAGE_SIZE;
          if (this.nextBeforeId !== null) url += '&before_id=' + this.nextBeforeId;
          const page = await getJson(url);
          const known = new Set(this.posts.map((p) => p.id));
          this.posts = this.posts.concat(page.items.filter((p) => !known.has(p.id)));
          for (const p of page.items) detailCache.set(p.id, p);
          this.nextBeforeId = page.next_before_id;
          this.postsLoaded = true;
        } catch (error) {
          this.postsError = 'De foto’s konden niet geladen worden. ' + error.message;
        } finally {
          this.postsLoading = false;
        }
      },

      openLightbox(post) {
        this.lightbox = post;
      },

      closeLightbox() {
        this.lightbox = null;
      },
    };
  });
});
