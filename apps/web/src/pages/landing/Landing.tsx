import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { SUPPORTED_LOCALES } from '@/i18n'

import './landing.css'
import type { HotspotId, YardScene } from './yardScene'
import { createYardScene } from './yardScene'

gsap.registerPlugin(ScrollTrigger)
// Tempo real mesmo em máquina lenta: com lag smoothing, quadro de 500 ms freia a animação
// e o título do hero parece não carregar.
gsap.ticker.lagSmoothing(0)

// Número do WhatsApp comercial vem do build (VITE_YARD_WHATSAPP, só dígitos com DDI);
// sem ele, os botões de WhatsApp caem no e-mail.
const WHATSAPP_NUMBER = String(import.meta.env.VITE_YARD_WHATSAPP ?? '').replace(/\D/g, '')
const EMAIL = 'contato@gplansis.com'

const CHAPTERS: { id: string; hotspot: HotspotId | null; bullets: boolean }[] = [
  { id: 'gate', hotspot: 'gate', bullets: true },
  { id: 'scale', hotspot: 'scale', bullets: true },
  { id: 'yard', hotspot: 'yard', bullets: true },
  { id: 'docks', hotspot: 'docks', bullets: true },
  { id: 'tower', hotspot: 'tower', bullets: true },
  { id: 'twin', hotspot: null, bullets: false },
]
const HOTSPOTS: HotspotId[] = ['gate', 'scale', 'yard', 'cold', 'docks', 'tower']
const KPIS = ['modules', 'kpis', 'trail', 'ai'] as const
const FEATURES = [
  'gate',
  'scheduling',
  'weighing',
  'moves',
  'docks',
  'iot',
  'tower',
  'integrations',
] as const

/** Ícones de traço simples: um por módulo, legíveis em 24px. */
const ICONS: Record<(typeof FEATURES)[number], string> = {
  gate: 'M3 20h18M5 20V9l7-5 7 5v11M9 20v-6h6v6M3 12h6',
  scheduling: 'M4 5h16v15H4zM4 9h16M8 3v4M16 3v4M8 13h3M8 16h6',
  weighing: 'M12 3v4M5 7h14l-2 7H7zM4 20h16M9 14l-1 6M15 14l1 6',
  moves: 'M3 17h2l2-5h7l2 5h2M7 17a2 2 0 1 0 4 0M13 17a2 2 0 1 0 4 0M14 12V7h4l3 5',
  docks: 'M3 21V8l9-5 9 5v13M7 21v-8h10v8M7 17h10',
  iot: 'M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13',
  tower: 'M9 21l1-10h4l1 10M7 11h10l-1-5H8zM12 3v3M4 21h16',
  integrations: 'M7 7h5v5H7zM12 12h5v5h-5zM12 9.5h5M9.5 12v5',
}

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  )
}

export default function Landing() {
  const { t, i18n } = useTranslation('landing')
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const storyRef = useRef<HTMLElement>(null)
  const labelRefs = useRef<Partial<Record<HotspotId, HTMLDivElement | null>>>({})
  const sceneRef = useRef<YardScene | null>(null)
  const [webgl, setWebgl] = useState(true)
  const [chapter, setChapter] = useState(-1)

  const mailto = `mailto:${EMAIL}?subject=${encodeURIComponent(t('cta.emailSubject'))}`
  const whatsapp = WHATSAPP_NUMBER
    ? `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(t('cta.whatsappMessage'))}`
    : mailto

  useEffect(() => {
    document.title = `${t('meta.brand')} — ${t('meta.tagline')}`
  }, [t])

  useEffect(() => {
    const root = rootRef.current
    const canvas = canvasRef.current
    if (!root || !canvas) return
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const lowPower =
      window.matchMedia('(max-width: 820px)').matches || (navigator.hardwareConcurrency ?? 8) <= 4

    let scene: YardScene | null = null
    try {
      scene = createYardScene(canvas, { reducedMotion, lowPower })
      sceneRef.current = scene
    } catch {
      // sem WebGL (máquina antiga, política corporativa): a página continua de pé
      setWebgl(false)
    }

    const ctx = gsap.context(() => {
      // abertura: o título entra antes da primeira rolagem
      gsap.from('[data-intro]', {
        y: 32,
        opacity: 0,
        duration: reducedMotion ? 0 : 0.9,
        ease: 'power3.out',
        stagger: 0.09,
        delay: 0.15,
      })

      ScrollTrigger.create({
        trigger: storyRef.current,
        start: 'top top',
        end: 'bottom bottom',
        onUpdate: (self) => scene?.setProgress(self.progress),
      })

      gsap.utils.toArray<HTMLElement>('[data-chapter]').forEach((element, index) => {
        ScrollTrigger.create({
          trigger: element,
          start: 'top 60%',
          end: 'bottom 40%',
          onToggle: (self) => {
            if (!self.isActive) return
            setChapter(index)
            scene?.setActive(CHAPTERS[index]?.hotspot ?? null)
          },
        })
        gsap.from(element.querySelector('.lp-chapter__card'), {
          x: -40,
          opacity: 0,
          duration: reducedMotion ? 0 : 0.8,
          ease: 'power3.out',
          scrollTrigger: { trigger: element, start: 'top 70%' },
        })
      })
      ScrollTrigger.create({
        trigger: storyRef.current,
        start: 'top top',
        end: 'top -40%',
        onEnterBack: () => {
          setChapter(-1)
          scene?.setActive(null)
        },
      })

      gsap.utils.toArray<HTMLElement>('[data-reveal]').forEach((element) => {
        gsap.from(element, {
          y: 40,
          opacity: 0,
          duration: reducedMotion ? 0 : 0.8,
          ease: 'power3.out',
          scrollTrigger: { trigger: element, start: 'top 88%' },
        })
      })

      gsap.utils.toArray<HTMLElement>('[data-count]').forEach((element) => {
        const target = Number(element.dataset.count)
        const state = { value: 0 }
        gsap.to(state, {
          value: target,
          duration: reducedMotion ? 0 : 1.6,
          ease: 'power2.out',
          delay: 0.6,
          onUpdate: () => {
            element.textContent = Math.round(state.value).toString()
          },
        })
      })
    }, root)

    // rótulos HTML presos aos pontos 3D: texto nítido e traduzível, sem sprite
    const placeLabels = () => {
      const current = sceneRef.current
      if (!current) return
      for (const spot of current.hotspots()) {
        const label = labelRefs.current[spot.id]
        if (!label) continue
        label.style.transform = `translate3d(${spot.x}px, ${spot.y}px, 0) translate(-50%, -120%)`
        label.style.opacity = spot.visible ? '1' : '0'
        label.classList.toggle('lp-label--active', spot.active)
      }
    }
    gsap.ticker.add(placeLabels)

    return () => {
      gsap.ticker.remove(placeLabels)
      ctx.revert()
      scene?.dispose()
      sceneRef.current = null
    }
  }, [])

  return (
    <div className={`lp${webgl ? '' : ' lp--no3d'}`} ref={rootRef}>
      <header className="lp-nav">
        <a className="lp-nav__brand" href="#top">
          <img src="/icons/icon.svg" alt="" width={32} height={32} />
          <span>{t('meta.brand')}</span>
        </a>
        <nav className="lp-nav__links">
          <a href="#funcionalidades">{t('nav.features')}</a>
          <a href="#gemeo">{t('nav.twin')}</a>
          <a href="#alimentos">{t('nav.food')}</a>
          <a href="#seguranca">{t('nav.security')}</a>
          <a href="#duvidas">{t('nav.faq')}</a>
        </nav>
        <div className="lp-nav__actions">
          <select
            aria-label={t('nav.language')}
            value={i18n.language}
            onChange={(event) => void i18n.changeLanguage(event.target.value)}
          >
            {SUPPORTED_LOCALES.map((locale) => (
              <option key={locale} value={locale}>
                {locale}
              </option>
            ))}
          </select>
          <Link className="lp-btn lp-btn--ghost" to="/login">
            {t('nav.login')}
          </Link>
          <a className="lp-btn lp-btn--primary lp-hide-sm" href={whatsapp} target="_blank" rel="noreferrer">
            {t('nav.demo')}
          </a>
        </div>
      </header>

      <section className="lp-story" ref={storyRef} id="top">
        <div className="lp-stage">
          <canvas ref={canvasRef} className="lp-stage__canvas" aria-hidden />
          <div className="lp-stage__shade" />
          <div className={`lp-stage__labels${chapter < 0 ? ' is-hidden' : ''}`} aria-hidden>
            {HOTSPOTS.map((id) => (
              <div
                key={id}
                className={`lp-label lp-label--${id}`}
                ref={(element) => {
                  labelRefs.current[id] = element
                }}
              >
                <span className="lp-label__dot" />
                {t(`label.${id}`)}
              </div>
            ))}
          </div>
          <div className="lp-progress" aria-hidden>
            {CHAPTERS.map((item, index) => (
              <span key={item.id} className={index <= chapter ? 'is-on' : ''} />
            ))}
          </div>
        </div>

        <div className="lp-chapters">
          <div className="lp-hero">
            <p className="lp-eyebrow" data-intro>
              <span className="lp-live" />
              {t('hero.eyebrow')}
            </p>
            <h1 className="lp-hero__title" data-intro>
              {t('hero.title')}
            </h1>
            <p className="lp-hero__lead" data-intro>
              {t('hero.lead')}
            </p>
            <div className="lp-hero__ctas" data-intro>
              <Link className="lp-btn lp-btn--primary lp-btn--lg" to="/login">
                {t('hero.primary')}
              </Link>
              <a className="lp-btn lp-btn--glass lp-btn--lg" href={whatsapp} target="_blank" rel="noreferrer">
                {t('hero.secondary')}
              </a>
            </div>
            <p className="lp-hero__note" data-intro>
              {t('hero.note')}
            </p>
            <div className="lp-kpis" data-intro>
              {KPIS.map((key) => (
                <div key={key} className="lp-kpi">
                  <div className="lp-kpi__value">
                    <span data-count={t(`kpi.${key}.value`)}>{t(`kpi.${key}.value`)}</span>
                    {key === 'trail' && t('kpi.trail.suffix')}
                  </div>
                  <div className="lp-kpi__label">{t(`kpi.${key}.label`)}</div>
                </div>
              ))}
            </div>
            <div className="lp-scroll" data-intro>
              <span className="lp-scroll__mouse" />
              {t('hero.scroll')}
            </div>
          </div>

          {CHAPTERS.map((item) => (
            <article
              key={item.id}
              className={`lp-chapter${item.id === 'twin' ? ' lp-chapter--center' : ''}`}
              data-chapter
              id={item.id === 'twin' ? 'gemeo' : undefined}
            >
              <div className="lp-chapter__card">
                <p className="lp-kicker">{t(`chapter.${item.id}.kicker`)}</p>
                <h2>{t(`chapter.${item.id}.title`)}</h2>
                <p>{t(`chapter.${item.id}.text`)}</p>
                {item.bullets && (
                  <ul className="lp-checks">
                    {(['b1', 'b2', 'b3'] as const).map((bullet) => (
                      <li key={bullet}>{t(`chapter.${item.id}.${bullet}`)}</li>
                    ))}
                  </ul>
                )}
                {item.id === 'twin' && (
                  <div className="lp-hero__ctas">
                    <Link className="lp-btn lp-btn--primary lp-btn--lg" to="/login">
                      {t('chapter.twin.cta')}
                    </Link>
                    <a className="lp-btn lp-btn--glass lp-btn--lg" href={whatsapp} target="_blank" rel="noreferrer">
                      {t('cta.primary')}
                    </a>
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="lp-section lp-problem">
        <div className="lp-wrap lp-split">
          <div data-reveal>
            <p className="lp-kicker">{t('problem.kicker')}</p>
            <h2 className="lp-h2">{t('problem.title')}</h2>
          </div>
          <div data-reveal>
            <ol className="lp-pains">
              {(['p1', 'p2', 'p3', 'p4'] as const).map((key) => (
                <li key={key}>{t(`problem.${key}`)}</li>
              ))}
            </ol>
            <p className="lp-answer">{t('problem.answer')}</p>
          </div>
        </div>
      </section>

      <section className="lp-section" id="funcionalidades">
        <div className="lp-wrap">
          <div data-reveal>
            <p className="lp-kicker">{t('features.kicker')}</p>
            <h2 className="lp-h2">{t('features.title')}</h2>
          </div>
          <div className="lp-grid">
            {FEATURES.map((key) => (
              <article key={key} className="lp-card" data-reveal>
                <span className="lp-card__icon">
                  <Icon path={ICONS[key]} />
                </span>
                <h3>{t(`features.${key}.title`)}</h3>
                <p>{t(`features.${key}.text`)}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section lp-food" id="alimentos">
        <div className="lp-wrap lp-split">
          <div data-reveal>
            <p className="lp-kicker lp-kicker--cold">{t('food.kicker')}</p>
            <h2 className="lp-h2">{t('food.title')}</h2>
            <p className="lp-lead">{t('food.text')}</p>
            <p className="lp-muted">{t('food.segments')}</p>
            <div className="lp-chips">
              {(['s1', 's2', 's3', 's4', 's5', 's6'] as const).map((key) => (
                <span key={key} className="lp-chip">
                  {t(`food.${key}`)}
                </span>
              ))}
            </div>
          </div>
          <ul className="lp-checks lp-checks--big" data-reveal>
            {(['i1', 'i2', 'i3', 'i4'] as const).map((key) => (
              <li key={key}>{t(`food.${key}`)}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="lp-section" id="seguranca">
        <div className="lp-wrap">
          <div data-reveal>
            <p className="lp-kicker">{t('security.kicker')}</p>
            <h2 className="lp-h2">{t('security.title')}</h2>
          </div>
          <div className="lp-grid lp-grid--4">
            {(['db', 'trail', 'roles', 'lgpd'] as const).map((key) => (
              <article key={key} className="lp-card lp-card--flat" data-reveal>
                <h3>{t(`security.${key}.title`)}</h3>
                <p>{t(`security.${key}.text`)}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section lp-steps-section">
        <div className="lp-wrap">
          <div data-reveal>
            <p className="lp-kicker">{t('steps.kicker')}</p>
            <h2 className="lp-h2">{t('steps.title')}</h2>
          </div>
          <ol className="lp-steps">
            {(['s1', 's2', 's3', 's4'] as const).map((key, index) => (
              <li key={key} data-reveal>
                <span className="lp-steps__n">{index + 1}</span>
                <h3>{t(`steps.${key}.title`)}</h3>
                <p>{t(`steps.${key}.text`)}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="lp-section" id="duvidas">
        <div className="lp-wrap lp-split">
          <div data-reveal>
            <p className="lp-kicker">{t('faq.kicker')}</p>
            <h2 className="lp-h2">{t('faq.title')}</h2>
          </div>
          <div className="lp-faq" data-reveal>
            {(['1', '2', '3', '4', '5'] as const).map((n) => (
              <details key={n}>
                <summary>{t(`faq.q${n}`)}</summary>
                <p>{t(`faq.a${n}`)}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-final">
        <div className="lp-wrap lp-final__inner" data-reveal>
          <p className="lp-kicker">{t('cta.kicker')}</p>
          <h2 className="lp-final__title">{t('cta.title')}</h2>
          <p className="lp-lead">{t('cta.text')}</p>
          <div className="lp-hero__ctas lp-hero__ctas--center">
            <a className="lp-btn lp-btn--primary lp-btn--xl" href={whatsapp} target="_blank" rel="noreferrer">
              {t('cta.primary')}
            </a>
            <Link className="lp-btn lp-btn--glass lp-btn--xl" to="/login">
              {t('cta.secondary')}
            </Link>
          </div>
          <a className="lp-muted lp-final__mail" href={mailto}>
            {t('cta.email')}
          </a>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer__inner">
          <span className="lp-nav__brand">
            <img src="/icons/icon.svg" alt="" width={24} height={24} />
            <span>{t('meta.brand')}</span>
          </span>
          <span className="lp-muted">{t('footer.text')}</span>
          <span className="lp-footer__links">
            <Link to="/login">{t('footer.login')}</Link>
            <a href={mailto}>{t('footer.contact')}</a>
          </span>
        </div>
      </footer>
    </div>
  )
}
