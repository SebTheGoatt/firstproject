// English / Español for the customer pages (home, booking, pay, visit).
//
// The pages are written in English. In Spanish mode this file translates them as they draw:
// static text, text the page adds later (prices, errors, the server's messages) and the
// placeholder / aria-label / title / alt attributes. Exact phrases come from ES; text with
// prices, dates or names in it comes from PATTERNS. Anything not listed stays as written.
//
// Language: ?lang=es|en in the address > the visitor's last choice > a Spanish browser.
(function () {
  const params = new URLSearchParams(location.search);
  let saved = null;
  try { saved = localStorage.getItem("lang"); } catch {}
  const fromUrl = params.get("lang");
  const browserEs = (navigator.languages || [navigator.language || ""]).some((l) => /^es\b/i.test(l));
  const lang = fromUrl === "es" || fromUrl === "en" ? fromUrl : saved === "es" || saved === "en" ? saved : browserEs ? "es" : "en";
  if (fromUrl === "es" || fromUrl === "en") { try { localStorage.setItem("lang", fromUrl); } catch {} }
  document.documentElement.lang = lang;

  const ES = {
    // ---------- Shared ----------
    "Skip to content": "Saltar al contenido",
    "Services": "Servicios",
    "Service areas": "Áreas de servicio",
    "How it works": "Cómo funciona",
    "Meet the crew": "Conoce al equipo",
    "Book Now": "Reservar",
    "Crew": "Equipo",
    "Home": "Inicio",
    "Main": "Principal",
    "Sections": "Secciones",
    "Footer": "Pie de página",
    "Book a service": "Reservar un servicio",
    "Book a Service": "Reservar un servicio",
    "View my visit": "Ver mi visita",
    "Crew sign-in": "Acceso del equipo",
    "Veteran-owned · Spring, TX": "De un veterano · Spring, TX",
    "Clean lawns. Stronger communities.": "Jardines limpios. Comunidades más fuertes.",
    "Get updates on this phone": "Recibir avisos en este teléfono",
    "Want a heads-up when we're on the way?": "¿Quieres un aviso cuando vayamos en camino?",
    "All done! Your before & after photos and receipt are below.": "¡Listo! Tus fotos de antes y después y tu recibo están abajo.",
    "We'll notify you when the crew is on the way, when your visit is done and when your card payment goes through, plus one note afterward asking how we did. Nothing else.": "Te avisaremos cuando el equipo vaya en camino, cuando termine tu visita y cuando se procese tu pago con tarjeta, más un mensaje después para preguntarte cómo lo hicimos. Nada más.",
    "On iPhone, tap Share, then Add to Home Screen, and open the app from there to get visit updates.": "En iPhone, toca Compartir, luego Agregar a pantalla de inicio y abre la app desde ahí para recibir avisos de tu visita.",
    "No problem. You can still check this page anytime.": "No hay problema. Puedes revisar esta página cuando quieras.",
    "Visit updates are on for this phone.": "Los avisos de tu visita están activados en este teléfono.",
    "We couldn't turn updates on. Please try again.": "No pudimos activar los avisos. Inténtalo de nuevo.",
    "Book again": "Reservar otra vez",
    "Close": "Cerrar",
    "Total": "Total",
    "Subtotal": "Subtotal",
    "No charge": "Sin costo",
    "Payment": "Pago",
    "Service": "Servicio",
    "Date": "Fecha",
    "Price": "Precio",
    "Lawn size": "Tamaño del césped",
    "Selected rate": "Tarifa elegida",
    "Base service fee": "Tarifa base del servicio",
    "Lawn size charge": "Cargo por tamaño",
    "Sales tax": "Impuesto sobre ventas",
    "Standard": "Estándar",
    "Plus": "Plus",
    "Premium": "Premium",
    "Neighborhood Block Lock": "Tarifa de vecindario",
    "Operational Target": "Tarifa operativa",
    "Bi-Weekly Demand": "Demanda quincenal",
    "Our most affordable per-visit rate.": "Nuestra tarifa por visita más económica.",
    "Our standard per-visit rate for most lawns.": "Nuestra tarifa por visita estándar para la mayoría de los jardines.",
    "For lawns that need a visit every two weeks in peak season. Still billed per visit.":
      "Para jardines que necesitan visita cada dos semanas en temporada alta. Se cobra por visita.",
    "Operational Base & Liability Allocation": "Base operativa y de responsabilidad",
    "Covers your crew, equipment and an optimized neighborhood route to your door.":
      "Cubre tu equipo de trabajo, las herramientas y una ruta optimizada por vecindario hasta tu puerta.",
    "Background-checked crew.": "Personal con verificación de antecedentes.",
    "Billed per visit. No subscription, no contract.": "Se cobra por visita. Sin suscripción ni contrato.",
    "Choose a rate to continue.": "Elige una tarifa para continuar.",
    "Choose a rate: Neighborhood Block Lock, Operational Target or Bi-Weekly Demand.":
      "Elige una tarifa: Tarifa de vecindario, Tarifa operativa o Demanda quincenal.",
    "Mowing": "Corte de césped",
    "Bin Cleaning": "Limpieza de botes",
    "Gutters": "Canaletas",
    "Lawn mowing": "Corte de césped",
    "Bin cleaning": "Limpieza de botes de basura",
    "Gutter cleaning": "Limpieza de canaletas",
    "Holiday lighting quote": "Cotización de luces navideñas",
    "Veterans of Foreign Wars (VFW)": "Veteranos de Guerras en el Extranjero (VFW)",
    "Neonatal intensive care (NICU) families": "familias de cuidados intensivos neonatales (NICU)",
    "At-risk youth programs": "programas para jóvenes en riesgo",
    "Install the app": "Instalar la app",
    "On iPhone: tap": "En iPhone: toca",
    "Share": "Compartir",
    ", then": ", luego",
    "Add to Home Screen": "Agregar a inicio",
    "to keep us one tap away.": "para tenernos a un toque.",
    "You're offline. Check your connection and try again.": "No tienes conexión. Revisa tu internet e intenta de nuevo.",
    "Checking your address…": "Revisando tu dirección…",
    "Please check the address and include your ZIP.": "Revisa la dirección e incluye tu código postal.",
    "Something went wrong. Please try again.": "Algo salió mal. Intenta de nuevo.",

    // ---------- Home ----------
    "Veteran-owned · Spring, TX area": "Negocio de un veterano · Área de Spring, TX",
    "Lawn Care, Run Like an Operation.": "Cuidado de césped, operado con precisión.",
    "Every visit is scheduled, routed and tracked. We run tight neighborhood routes so the crew's time goes into your lawn, not the road, and you get an alert when we're on the way.":
      "Cada visita se programa, se planifica en ruta y se sigue en vivo. Trabajamos en rutas compactas por vecindario para que el tiempo del equipo se use en tu jardín, no en el camino, y te avisamos cuando vamos en camino.",
    "Explore Services": "Ver servicios",
    "Next open day": "Próximo día disponible",
    "Next available service day": "Próximo día de servicio disponible",
    "Book this day": "Reservar este día",
    "See the booking page": "Ver la página de reservas",
    "Our Services": "Nuestros servicios",
    "Start with a mow, then add what your home needs.": "Empieza con un corte de césped y agrega lo que tu hogar necesite.",
    "Lawn Mowing": "Corte de césped",
    "Clean cuts. Crisp edges. A lawn you're proud of.": "Cortes limpios. Bordes definidos. Un césped del que te sentirás orgulloso.",
    "Your final price depends on lawn size and the rate you select.": "Tu precio final depende del tamaño del césped y de la tarifa que elijas.",
    "Calculate My Price": "Calcular mi precio",
    "Trash bins build up bacteria like E. coli and Salmonella and draw flies, roaches and rodents to your door. A hose rinse doesn't remove that buildup. We clean and sanitize every bin.":
      "Los botes de basura acumulan bacterias como E. coli y Salmonella y atraen moscas, cucarachas y roedores a tu puerta. Enjuagarlos con manguera no quita esa suciedad. Nosotros limpiamos y desinfectamos cada bote.",
    "Add to any lawn mowing visit.": "Agrégalo a cualquier visita de corte de césped.",
    "Add Bin Cleaning": "Agregar limpieza de botes",
    "Gutter Cleaning": "Limpieza de canaletas",
    "Clear gutters. Better water flow.": "Canaletas limpias. Mejor flujo de agua.",
    "Add Gutter Cleaning": "Agregar limpieza de canaletas",
    "Holiday Lighting": "Luces navideñas",
    "Holiday lighting, professionally installed to fit your home.": "Luces navideñas instaladas profesionalmente a la medida de tu hogar.",
    "Custom Quote": "Cotización personalizada",
    "Pricing depends on home size, roofline, and installation needs.":
      "El precio depende del tamaño de la casa, el techo y la instalación.",
    "Install window: Oct 15 – Jan 15": "Temporada de instalación: 15 oct – 15 ene",
    "Every quote starts with a custom lighting plan drawn for your home's roofline. Installs are scheduled by neighborhood, on the same routes as our lawn work.":
      "Cada cotización empieza con un plan de luces hecho a la medida del techo de tu casa. Las instalaciones se programan por vecindario, en las mismas rutas de nuestro trabajo de jardín.",
    "Get a Quote": "Pedir cotización",
    "Why homeowners book with us": "Por qué nos eligen",
    "Neighborhood Routing": "Rutas por vecindario",
    "Each day's route is planned the evening before, stop by stop.": "La ruta de cada día se planifica la tarde anterior, parada por parada.",
    "Live Visit Tracking": "Seguimiento de tu visita en vivo",
    "An alert when the crew is on the way, and a live page for every visit.": "Un aviso cuando el equipo va en camino y una página en vivo para cada visita.",
    "Secure Billing": "Pagos seguros",
    "Cards are paid through Stripe's encrypted checkout. Every visit ends with a digital receipt and before & after photos.": "Las tarjetas se pagan en el pago cifrado de Stripe. Cada visita termina con un recibo digital y fotos de antes y después.",
    "Do We Service Your Area?": "¿Damos servicio en tu área?",
    "We keep our routes tight so the crew spends time on lawns, not on the road. Check your address, or find your neighborhood below.":
      "Mantenemos rutas cortas para que el equipo pase su tiempo en los jardines, no en la carretera. Revisa tu dirección o busca tu vecindario abajo.",
    "Check your address": "Revisa tu dirección",
    "Check": "Revisar",
    "House number, street, city and ZIP. We only check it; nothing is saved.": "Número, calle, ciudad y código postal. Solo la revisamos; no se guarda nada.",
    "Please enter your full address with the house number, e.g. 4726 Whispering Rock Ln, Spring, TX 77388.":
      "Escribe tu dirección completa con el número de casa, por ejemplo: 4726 Whispering Rock Ln, Spring, TX 77388.",
    "Neighborhoods we serve": "Vecindarios donde trabajamos",
    "Book a service.": "Reservar un servicio.",
    "Book in this area": "Reservar en esta área",
    "Shaded areas are where we work today. Tap an area or a neighborhood to zoom in.":
      "Las áreas sombreadas son donde trabajamos hoy. Toca un área o un vecindario para acercar.",
    "Map": "Mapa",
    "Map marker": "Marcador del mapa",
    "Zoom in": "Acercar",
    "Zoom out": "Alejar",
    "Toggle attribution": "Mostrar créditos",
    "Use Ctrl + scroll to zoom the map": "Usa Ctrl + rueda para hacer zoom en el mapa",
    "Use two fingers to move the map": "Usa dos dedos para mover el mapa",
    "Map of our service areas around Spring, Klein, New Caney, Splendora, Cleveland, Plum Grove and Colony Ridge, Texas":
      "Mapa de nuestras áreas de servicio en Spring, Klein, New Caney, Splendora, Cleveland, Plum Grove y Colony Ridge, Texas",
    "How It Works": "Cómo funciona",
    "Choose Your Service": "Elige tu servicio",
    "Pick mowing, your lawn size and impact level, and any add-ons for the visit.":
      "Elige el corte de césped, el tamaño de tu césped, tu tarifa y cualquier extra para la visita.",
    "Confirm Your Details": "Confirma tus datos",
    "Enter your address and day. We check your area and show your full price with tax before you book.":
      "Escribe tu dirección y el día. Revisamos tu área y te mostramos el precio completo con impuestos antes de reservar.",
    "Book Your Visit": "Reserva tu visita",
    "Pay cash to the crew or by card. We lock the route at 5 PM the day before and alert you when we're on the way.":
      "Paga en efectivo al equipo o con tarjeta. Cerramos la ruta a las 5 PM del día anterior y te avisamos cuando vamos en camino.",
    "Meet the Crew": "Conoce al equipo",
    "Tight route density.": "Rutas compactas.",
    "We work each neighborhood on a set rotation, so the crew's time goes into your lawn, not the road.":
      "Trabajamos cada vecindario en una rotación fija, para que el tiempo del equipo se use en tu jardín, no en el camino.",
    "Run with Marine Corps discipline: a planned route every day, a live page for every visit, and card payments through Stripe's encrypted checkout.":
      "Con la disciplina del Cuerpo de Marines: una ruta planificada cada día, una página en vivo para cada visita y pagos con tarjeta en el pago cifrado de Stripe.",
    "Marine-led operations · Planned daily routes · Encrypted card payments":
      "Dirigido por un Marine · Rutas planificadas cada día · Pagos con tarjeta cifrados",
    "Real people from the neighborhood, led by a veteran. Here's who shows up at your door.":
      "Gente real del vecindario, dirigida por un veterano. Ellos son quienes llegan a tu puerta.",
    "See everyone's work": "Ver el trabajo de todos",
    "Put your lawn on the route.": "Pon tu jardín en la ruta.",
    "Booking takes about a minute, and you'll see your full price before you book.":
      "Reservar toma como un minuto y verás tu precio completo antes de confirmar.",

    // ---------- Booking ----------
    "Calculate your mowing price, add any extras, and book your visit. You'll see the full itemized total before you book.":
      "Calcula el precio de tu corte, agrega extras y reserva tu visita. Verás el total detallado antes de confirmar.",
    "Where we service": "Dónde trabajamos",
    "How large is your lawn?": "¿Qué tan grande es tu césped?",
    "Enter lawn square footage": "Escribe los pies cuadrados del césped",
    "sq ft": "pies²",
    "Enter your estimated mowable lawn area in square feet.": "Escribe el área aproximada de césped a cortar, en pies cuadrados.",
    "Enter your lawn size in square feet.": "Escribe el tamaño de tu césped en pies cuadrados.",
    "Lawn size must be a whole number of square feet.": "El tamaño del césped debe ser un número entero de pies cuadrados.",
    "Lawn size must be greater than zero.": "El tamaño del césped debe ser mayor que cero.",
    "Choose your rate": "Elige tu tarifa",
    "Rate per square foot": "Tarifa por pie cuadrado",
    "Essential lawn maintenance at our most affordable rate.": "Mantenimiento esencial del césped con nuestra tarifa más económica.",
    "A balanced option for dependable lawn care.": "Una opción equilibrada para un cuidado confiable del césped.",
    "Our highest service rate for customers who prefer the premium option.": "Nuestra tarifa más alta, para quienes prefieren la opción premium.",
    "Choose Standard, Plus or Premium to continue.": "Elige Estándar, Plus o Premium para continuar.",
    "Choose a rate: Standard, Plus or Premium.": "Elige una tarifa: Estándar, Plus o Premium.",
    "Lawn Mowing estimate": "Estimado de corte de césped",
    "Enter above": "Escríbelo arriba",
    "Enter above or add your address": "Escríbelo arriba o agrega tu dirección",
    "Your address": "Tu dirección",
    "Your lawn": "Tu césped",
    "Property Infrastructure Configuration:": "¿Qué área cortamos?",
    "Standard Managed Footprint": "Área principal",
    "Full Estate Scope": "Propiedad completa",
    "Main or fenced yard only": "Solo el jardín principal o cercado",
    "The whole property, minus the house": "Toda la propiedad, menos la casa",
    "✓ Price locked. You pay this total for the area you chose. No surprise changes on site.":
      "✓ Precio fijo. Pagas este total por el área que elegiste. Sin cambios sorpresa en el lugar.",
    "✓ Price locked": "✓ Precio fijo",
    "You pay this total for the area you chose. No surprise changes on site.": "Pagas este total por el área que elegiste. Sin cambios sorpresa en el lugar.",
    "Yard only": "Solo el jardín",
    "Full property": "Propiedad completa",
    "Included": "Incluido",
    "Pick your address to size your lawn": "Elige tu dirección para medir tu césped",
    "Know your exact size? Edit": "¿Sabes el tamaño exacto? Edítalo",
    "Your lawn size": "Tamaño de tu césped",
    "Lawn square footage": "Pies cuadrados de césped",
    "Mowable lawn area only. The crew confirms it on site.": "Solo el área de césped a cortar. El equipo lo confirma en el lugar.",
    "Your size. The crew confirms it on site.": "Tu medida. El equipo la confirma en el lugar.",
    "Add your address in step 1": "Agrega tu dirección en el paso 1",
    "Add your address in step 1 to see your final total.": "Agrega tu dirección en el paso 1 para ver tu total final.",
    "Pick your address from the list first so we can size your lawn.": "Primero elige tu dirección de la lista para medir tu césped.",
    "Enter your mowable lawn area in square feet. Not sure? Skip it: we'll estimate it from your address in step 4.":
      "Escribe el área de césped a cortar, en pies cuadrados. ¿No estás seguro? Déjalo: lo estimamos con tu dirección en el paso 4.",
    "✓ Address verified · lawn size estimated": "✓ Dirección verificada · tamaño del césped estimado",
    "Choose above": "Elígela arriba",
    "Estimated subtotal": "Subtotal estimado",
    "Calculated at checkout": "Se calcula al pagar",
    "Estimated total": "Total estimado",
    "Your order generates": "Tu pedido genera",
    "✓ Package includes": "✓ El paquete incluye",
    "Precision Turf Maintenance Profile": "Perfil de mantenimiento de césped",
    "Direct Your Local Community Impact Token": "Elige a quién ayuda tu pedido",
    "Part of every order goes to a local cause. Pick where yours goes.": "Una parte de cada pedido va a una causa local. Elige a dónde va la tuya.",
    "Holiday toy drive for local kids": "Colecta de juguetes navideños para niños locales",
    "Helps buy holiday toys for kids in our service area.": "Ayuda a comprar juguetes navideños para niños de nuestra zona de servicio.",
    "Veterans of Foreign Wars (VFW)": "Veteranos de Guerras en el Extranjero (VFW)",
    "Helps local veterans and their families through a VFW post in our area.": "Ayuda a veteranos locales y sus familias a través de un puesto del VFW de nuestra zona.",
    "Neonatal intensive care (NICU) families": "Familias con bebés en cuidados intensivos neonatales (NICU)",
    "Helps families whose newborns are in neonatal intensive care.": "Ayuda a familias cuyos recién nacidos están en cuidados intensivos neonatales.",
    "for the cause you pick in step 6": "para la causa que elijas en el paso 6",
    "✓ Your pick is saved with your booking. What your order generates goes to that cause, and so does anything extra you give the crew.":
      "✓ Tu elección se guarda con tu reserva. Lo que genera tu pedido va a esa causa, y también cualquier extra que le des al equipo.",
    "for local VFW, NICU & at-risk youth programs": "para programas locales de VFW, NICU y jóvenes en riesgo",
    "Add-ons": "Extras",
    "(optional)": "(opcional)",
    "Add-ons to your mowing visit": "Extras para tu visita de corte",
    "Added to your mowing visit": "Se agrega a tu visita de corte",
    "Sanitized, not just rinsed": "Desinfectado, no solo enjuagado",
    "Recommended": "Recomendado",
    "Free quote": "Cotización gratis",
    "Address & day": "Dirección y día",
    "Service address": "Dirección del servicio",
    "House number, street, city and ZIP.": "Número, calle, ciudad y código postal.",
    "Pick your address from the list.": "Elige tu dirección de la lista.",
    "Start typing your address…": "Empieza a escribir tu dirección…",
    "Please choose your address from the list.": "Elige tu dirección de la lista.",
    "Service day": "Día del servicio",
    "Next-day bookings close at 5 PM.": "Las reservas para el día siguiente cierran a las 5 PM.",
    "Review your order": "Revisa tu pedido",
    "Order summary": "Resumen del pedido",
    "Add your lawn size, rate and address to see your final total.": "Agrega el tamaño del césped, la tarifa y la dirección para ver tu total final.",
    "We don't serve that address yet.": "Todavía no damos servicio en esa dirección.",
    "Holiday lighting is a free quote: the crew takes a look and you decide later. Nothing is charged for it.":
      "Las luces navideñas son una cotización gratis: el equipo revisa y tú decides después. No se cobra nada por ella.",
    "Your crew confirms the lawn size on site; the price only changes if it's different.":
      "El equipo confirma el tamaño del césped en el lugar; el precio solo cambia si es diferente.",
    "Pay your way": "Paga como prefieras",
    "Payment method": "Forma de pago",
    "Cash to the crew": "Efectivo al equipo",
    "Pay when we arrive or when we finish.": "Paga cuando lleguemos o cuando terminemos.",
    "Card, Apple Pay or Google Pay": "Tarjeta, Apple Pay o Google Pay",
    "Pay securely now, or after the visit.": "Paga de forma segura ahora o después de la visita.",
    "Coming soon.": "Muy pronto.",
    "No tip necessary. Donations are always welcome, never taxed, and go to": "No se necesita propina. Las donaciones siempre son bienvenidas, no pagan impuestos y van para",
    ". We're a veteran-owned business.": ". Somos un negocio de un veterano.",
    "Your details": "Tus datos",
    "Full name": "Nombre completo",
    "Mobile phone": "Teléfono celular",
    "We text your access code, and again when the crew is on the way.": "Te enviamos tu código de acceso por mensaje, y otra vez cuando el equipo vaya en camino.",
    "Book service": "Reservar servicio",
    "Booking…": "Reservando…",
    "Your access code": "Tu código de acceso",
    "Save it: it opens your visit page with arrival time, payment and before & after photos.":
      "Guárdalo: abre la página de tu visita con la hora de llegada, el pago y las fotos de antes y después.",
    "Or pay later; we'll text you this link when the job's done.": "O paga después; te enviaremos este enlace por mensaje cuando terminemos.",
    "Open your payment page": "Abrir tu página de pago",
    "Your final price is set on site. We'll text you this link when the job's done.": "Tu precio final se fija en el lugar. Te enviaremos este enlace por mensaje cuando terminemos.",
    "You chose cash: pay the crew when they arrive.": "Elegiste efectivo: paga al equipo cuando llegue.",
    "Card payments aren't available yet. Please choose cash.": "Los pagos con tarjeta aún no están disponibles. Elige efectivo.",
    "Bin cleaning and gutters are add-ons to a mowing visit. Book mowing and add them on.":
      "La limpieza de botes y de canaletas son extras de una visita de corte. Reserva el corte y agrégalos.",
    "That day is fully booked. Please choose another day.": "Ese día ya está lleno. Elige otro día.",
    "Address lookup is temporarily unavailable. Please try again in a minute.": "La búsqueda de direcciones no está disponible por ahora. Intenta de nuevo en un minuto.",
    "We couldn't find that address. Please check the street name and include city, state and ZIP.":
      "No encontramos esa dirección. Revisa el nombre de la calle e incluye ciudad, estado y código postal.",
    "Too many checks. Please wait a few minutes.": "Demasiadas búsquedas. Espera unos minutos.",

    // ---------- Pay ----------
    "Data from": "Datos de",
    "Confirming your payment…": "Confirmando tu pago…",
    "Your final price is set when the crew finishes the job. We'll text you this link then.":
      "Tu precio final se fija cuando el equipo termina el trabajo. Te enviaremos este enlace por mensaje en ese momento.",
    "Your final price is set when the crew finishes. We'll text you this link then.":
      "Tu precio final se fija cuando el equipo termina. Te enviaremos este enlace por mensaje en ese momento.",
    "Online card payments aren't available right now. You can pay the crew in cash.": "Los pagos con tarjeta en línea no están disponibles ahora. Puedes pagar al equipo en efectivo.",
    "Card payments aren't set up yet. You can pay the crew in cash.": "Los pagos con tarjeta aún no están listos. Puedes pagar al equipo en efectivo.",
    "Card payments are temporarily unavailable. Please try again shortly.": "Los pagos con tarjeta no están disponibles por el momento. Intenta de nuevo en un rato.",
    "Add a donation?": "¿Quieres agregar una donación?",
    "No tip necessary. Donations are always welcome and never taxed. We're a veteran-owned business, and we pass every donation on:":
      "No se necesita propina. Las donaciones siempre son bienvenidas y no pagan impuestos. Somos un negocio de un veterano y entregamos cada donación:",
    "No thanks": "No, gracias",
    "Other": "Otra",
    "Donation amount ($)": "Monto de la donación ($)",
    "Donation amount": "Monto de la donación",
    "Pay with card, Apple Pay or Google Pay on Stripe's secure page. We never see your card number.":
      "Paga con tarjeta, Apple Pay o Google Pay en la página segura de Stripe. Nunca vemos el número de tu tarjeta.",
    "Because donations are paid through our business, they aren't tax-deductible for you.":
      "Como las donaciones se pagan a través de nuestro negocio, no son deducibles de impuestos para ti.",
    "Pay securely": "Pagar de forma segura",
    "Opening secure checkout…": "Abriendo el pago seguro…",
    "We're still confirming your payment. You'll see it here shortly; no need to pay again.":
      "Todavía estamos confirmando tu pago. Lo verás aquí en breve; no necesitas pagar de nuevo.",
    "Set on site": "Se fija en el lugar",
    "This visit is already paid. Thank you!": "Esta visita ya está pagada. ¡Gracias!",
    "We couldn't find that payment link.": "No encontramos ese enlace de pago.",
    "We couldn't load this payment.": "No pudimos cargar este pago.",

    // ---------- Visit ----------
    "Your visit": "Tu visita",
    "Enter your access code": "Escribe tu código de acceso",
    "It's on your booking confirmation and in our text message. It looks like": "Está en la confirmación de tu reserva y en nuestro mensaje de texto. Se ve así:",
    "Access code": "Código de acceso",
    "See my visit": "Ver mi visita",
    "Booked": "Reservado",
    "Route planned": "Ruta planeada",
    "On the way": "En camino",
    "Done": "Terminado",
    "Your crew is on the way!": "¡Tu equipo va en camino!",
    "We'll plan the route at 5 PM the day before and text you when the crew is on the way.":
      "Planearemos la ruta a las 5 PM del día anterior y te avisaremos por mensaje cuando el equipo vaya en camino.",
    "Your crew": "Tu equipo",
    "See their profile and work": "Ver su perfil y trabajo",
    "Pay now": "Pagar ahora",
    "Open payment page": "Abrir página de pago",
    "Your price is set on site when the job is done. Texas sales tax is added.": "Tu precio se fija en el lugar al terminar el trabajo. Se agrega el impuesto sobre ventas de Texas.",
    "No tip necessary. Donations are always welcome and go to the VFW (33%), NICU families (33%) and at-risk youth programs (34%).":
      "No se necesita propina. Las donaciones siempre son bienvenidas y van para VFW (33%), familias de NICU (33%) y programas para jóvenes en riesgo (34%).",
    "Where your donation goes": "A dónde va tu donación",
    "Before & after": "Antes y después",
    "How did we do?": "¿Cómo lo hicimos?",
    "If we did a good job, a quick Google review helps a veteran-owned local business. It takes about a minute.":
      "Si hicimos un buen trabajo, una reseña rápida en Google ayuda a un negocio local de veteranos. Toma como un minuto.",
    "Leave a Google review": "Dejar una reseña en Google",
    "Before": "Antes",
    "After": "Después",
    "Your crew will add before and after photos during the visit.": "Tu equipo agregará fotos de antes y después durante la visita.",
    "Use a different code": "Usar otro código",
    "Codes have 8 letters and numbers, like K7MX-3QPA.": "Los códigos tienen 8 letras y números, como K7MX-3QPA.",
    "No connection. Please try again.": "Sin conexión. Intenta de nuevo.",
    "We couldn't open that visit.": "No pudimos abrir esa visita.",
    "We couldn't find that code. Check it and try again.": "No encontramos ese código. Revísalo e intenta de nuevo.",
    "Too many tries. Please wait a few minutes.": "Demasiados intentos. Espera unos minutos.",
    " in cash": " en efectivo",
    " by card": " con tarjeta",
    ". Thank you!": ". ¡Gracias!",
  };

  // English weekday / month names inside server messages ("Friday, Oct 16").
  const DAYS = { Monday: "lunes", Tuesday: "martes", Wednesday: "miércoles", Thursday: "jueves", Friday: "viernes", Saturday: "sábado", Sunday: "domingo" };
  const MONTHS = { January: "enero", February: "febrero", March: "marzo", April: "abril", May: "mayo", June: "junio", July: "julio",
    August: "agosto", September: "septiembre", October: "octubre", November: "noviembre", December: "diciembre",
    Jan: "ene", Feb: "feb", Mar: "mar", Apr: "abr", Jun: "jun", Jul: "jul", Aug: "ago", Sep: "sep", Oct: "oct", Nov: "nov", Dec: "dic" };
  const esDate = (s) => s.replace(/\b([A-Z][a-z]+)\b/g, (w) => DAYS[w] || MONTHS[w] || w);
  const one = (s) => ES[s] ?? s;
  const services = (s) => s.split(" + ").map(one).join(" + ");
  const charityList = (s) => s.split(/, | and /).map((part) => part.replace(/^(\$[\d,.]+) to (.+)$/, (_, a, n) => `${a} para ${one(n)}`)).join(", ");

  const PATTERNS = [
    // Page titles end with the business name, whatever it is.
    [/^(Book a [Ss]ervice|Pay|Your Visit) \| (.+)$/, (m) => `${{ "Book a Service": "Reservar un servicio", "Book a service": "Reservar un servicio", Pay: "Pagar", "Your Visit": "Tu visita" }[m[1]]} | ${m[2]}`],
    [/^(.+) \| Mowing, Bin Cleaning & Gutters in Spring, TX$/, (m) => `${m[1]} | Corte de césped, limpieza de botes y canaletas en Spring, TX`],
    [/^Starting at (\$[\d,.]+) per visit$/, (m) => `Desde ${m[1]} por visita`],
    [/^\+(\$[\d,.]+) per visit$/, (m) => `+${m[1]} por visita`],
    [/^Mowing starts at (\$[\d,.]+) per visit in every area\.$/, (m) => `El corte de césped empieza en ${m[1]} por visita en todas las áreas.`],
    [/^from (\$[\d,.]+)$/, (m) => `desde ${m[1]}`],
    [/^Mowing from (\$[\d,.]+) per visit$/, (m) => `Corte desde ${m[1]} por visita`],
    [/^Show (.+) on the map$/, (m) => `Mostrar ${m[1]} en el mapa`],
    [/^(.+): mowing (\$[\d,.]+) per visit plus a per-sq-ft rate$/, (m) => `${m[1]}: corte desde ${m[2]} por visita más una tarifa por pie²`],
    [/^(Neighborhood Block Lock|Operational Target|Bi-Weekly Demand) · (\$[\d.]+) \/ sq\. ft\.$/, (m) => `${ES[m[1]]} · ${m[2]} / pie²`],
    [/^Includes (.+) commercial liability coverage while we're on your property\.$/, (m) => `Incluye cobertura de responsabilidad comercial de ${m[1]} mientras estamos en tu propiedad.`],
    [/^Next-day booking closes at (\d+ [AP]M) sharp\.$/, (m) => `Las reservas para el día siguiente cierran a las ${m[1]} en punto.`],
    [/^Only (\d+) spots? left on (.+)'s route\.$/, (m) => m[1] === "1" ? `Solo queda 1 lugar en la ruta del ${m[2]}.` : `Solo quedan ${m[1]} lugares en la ruta del ${m[2]}.`],
    [/^(.+)'s route is full\. Pick another day when you book\.$/, (m) => `La ruta del ${m[1]} está llena. Elige otro día al reservar.`],
    [/^Next-day booking closes at (\d+ [AP]M) Central\.$/, (m) => `Las reservas para el día siguiente cierran a las ${m[1]} (hora del centro).`],
    [/^Earliest available: (.+)\. Next-day bookings close at (\d+ [AP]M)\.$/, (m) => `Primer día disponible: ${m[1]}. Las reservas para el día siguiente cierran a las ${m[2]}.`],
    [/^That day's route is already locked\. The earliest available day is (.+)\.$/, (m) => `La ruta de ese día ya está cerrada. El primer día disponible es ${esDate(m[1])}.`],
    [/^Please book within the next (\d+) days\.$/, (m) => `Reserva dentro de los próximos ${m[1]} días.`],
    [/^(.+) is offered for service dates (.+)\.$/, (m) => `${one(m[1])} se ofrece para fechas de servicio del ${esDate(m[2]).replace(" – ", " al ")}.`],
    [/^The smallest lawn we can book online is ([\d,]+) sq ft\.$/, (m) => `El césped más pequeño que podemos reservar en línea es de ${m[1]} pies².`],
    [/^Lawns over ([\d,]+) sq ft \(2 acres\) are quoted in person\..*$/, (m) => `Los céspedes de más de ${m[1]} pies² (2 acres) se cotizan en persona.`],
    [/^Sorry, that address is outside our current service areas: (.+)\.$/, (m) => `Lo sentimos, esa dirección está fuera de nuestras áreas de servicio actuales: ${m[1]}.`],
    [/^Donations can be between \$0 and (\$[\d,]+)\.$/, (m) => `Las donaciones pueden ser de $0 a ${m[1]}.`],
    [/^(\$[\d,.]+) before tax$/, (m) => `${m[1]} antes de impuestos`],
    [/^(\$[\d,.]+) \+ tax$/, (m) => `${m[1]} + impuestos`],
    [/^([\d,]+) sq ft$/, (m) => `${m[1]} pies²`],
    [/^Main or fenced yard only · ~([\d,]+) sq ft$/, (m) => `Solo el jardín principal o cercado · ~${m[1]} pies²`],
    [/^The whole property, minus the house · ~([\d,]+) sq ft$/, (m) => `Toda la propiedad, menos la casa · ~${m[1]} pies²`],
    [/^([\d,]+) sq ft · (Yard only|Full property)$/, (m) => `${m[1]} pies² · ${ES[m[2]]}`],
    [/^([\d,]+) sq ft · (Yard only|Full property) \(price locked\)$/, (m) => `${m[1]} pies² · ${ES[m[2]]} (precio fijo)`],
    [/^Area mowed: (.+)$/, (m) => `Área cortada: ${ES[m[1]] ?? m[1]}`],
    [/^([\d,]+) sq ft \(estimated\)$/, (m) => `${m[1]} pies² (estimado)`],
    [/^Estimated from (\d+) lawns we've measured in (.+)\. Change it if you know your size; the crew confirms it on site\.$/,
      (m) => `Estimado con ${m[1]} jardines que medimos en ${m[2]}. Cámbialo si conoces el tamaño; el equipo lo confirma en el lugar.`],
    [/^Estimated from (\d+) lawns we've measured in (.+)\. The crew confirms it on site\.$/,
      (m) => `Estimado con ${m[1]} jardines que medimos en ${m[2]}. El equipo lo confirma en el lugar.`],
    [/^Estimated from a typical lot in (.+)\. The crew confirms it on site\.$/,
      (m) => `Estimado con un terreno típico de ${m[1]}. El equipo lo confirma en el lugar.`],
    [/^Estimated from a typical lot in (.+)\. Change it if you know your size; the crew confirms it on site\.$/,
      (m) => `Estimado con un terreno típico de ${m[1]}. Cámbialo si conoces el tamaño; el equipo lo confirma en el lugar.`],
    [/^(\$[\d.]+) \/ sq\. ft\.$/, (m) => `${m[1]} / pie²`],
    [/^(Standard|Plus|Premium) · (\$[\d.]+) \/ sq\. ft\.$/, (m) => `${one(m[1])} · ${m[2]} / pie²`],
    [/^✓ Good news: you're in our (.+) area\.$/, (m) => `✓ ¡Buenas noticias! Estás en nuestra área de ${m[1]}.`],
    [/^Good news: you're in our (.+) area\..*$/, (m) => `¡Buenas noticias! Estás en nuestra área de ${m[1]}.`],
    [/^✓ Yes! You're in our (.+) area\.$/, (m) => `✓ ¡Sí! Estás en nuestra área de ${m[1]}.`],
    [/^Lawn mowing · (.+?) · (Yard only|Full property) · ([\d,]+) sq ft$/, (m) => `Corte de césped · ${one(m[1])} · ${ES[m[2]]} · ${m[3]} pies²`],
    [/^Lawn mowing · (.+?) · ([\d,]+) sq ft( \(estimated\))?$/, (m) => `Corte de césped · ${one(m[1])} · ${m[2]} pies²${m[3] ? " (estimado)" : ""}`],
    [/^Lawn size charge \(([\d,]+) × (\$[\d.]+) \/ sq\. ft\.\)$/, (m) => `Cargo por tamaño (${m[1]} × ${m[2]} / pie²)`],
    [/^Add-on: (.+)$/, (m) => `Extra: ${one(m[1])}`],
    [/^Sales tax \(([\d.]+%)\)$/, (m) => `Impuesto sobre ventas (${m[1]})`],
    [/^Texas sales tax \(([\d.]+%)\)$/, (m) => `Impuesto sobre ventas de Texas (${m[1]})`],
    [/^You're booked for (.+)\.$/, (m) => `¡Listo! Tu cita es el ${m[1]}.`],
    [/^We'll text (.+) when the crew is headed to (.+)\.$/, (m) => `Te enviaremos un mensaje al ${m[1]} cuando el equipo vaya en camino a ${m[2]}.`],
    [/^for (.+)$/, (m) => ES[m[1]] ? `para ${ES[m[1]]}` : null],
    [/^(\$[\d,.]+) \/ visit$/, (m) => `${m[1]} / visita`],
    [/^From (\$[\d,.]+) \/ visit$/, (m) => `Desde ${m[1]} / visita`],
    [/^✓ Package includes (\$[\d,.]+) for (.+)\. Thank you!$/, (m) => `✓ El paquete incluye ${m[1]} para ${ES[m[2]] ?? m[2]}. ¡Gracias!`],
    [/^Your order generates (\$[\d,.]+) for (.+)\. Thank you!$/, (m) => ES[m[2]] ? `Tu pedido genera ${m[1]} para ${ES[m[2]]}. ¡Gracias!` : null],
    [/^Your order generates (\$[\d,.]+) for local VFW, NICU & at-risk youth programs\. Thank you!$/, (m) => `Tu pedido genera ${m[1]} para programas locales de VFW, NICU y jóvenes en riesgo. ¡Gracias!`],
    [/^★ Your order generates (\$[\d,.]+) for local VFW, NICU & at-risk youth programs \((\w+), (\d+)% of your price\)\. It's included in your total, not added on\.$/,
      (m) => `★ Tu pedido genera ${m[1]} para programas locales de VFW, NICU y jóvenes en riesgo (${one(m[2])}, ${m[3]}% de tu precio). Ya está incluido en tu total, no se suma.`],
    [/^Your order generates (\$[\d,.]+) \((\w+)\)$/, (m) => `Tu pedido genera ${m[1]} (${one(m[2])})`],
    [/^Pay (\$[\d,.]+) now$/, (m) => `Pagar ${m[1]} ahora`],
    [/^Pay (\$[\d,.]+) securely$/, (m) => `Pagar ${m[1]} de forma segura`],
    [/^Hi (.+)$/, (m) => `Hola ${m[1]}`],
    [/^Mowing \((.+?), ([\d,]+) sq ft\)$/, (m) => `Corte de césped (${one(m[1])}, ${m[2]} pies²)`],
    [/^Mowing, (.+?) · ([\d,]+) sq ft$/, (m) => `Corte de césped, ${one(m[1])} · ${m[2]} pies²`],
    [/^Where your (\$[\d,.]+) goes$/, (m) => `A dónde van tus ${m[1]}`],
    [/^(Veterans of Foreign Wars \(VFW\)|Neonatal intensive care \(NICU\) families|At-risk youth programs) \((\d+)%\)$/, (m) => `${one(m[1])} (${m[2]}%)`],
    [/^(\d+)% to (.+), (\d+)% to (.+) and (\d+)% to (.+)$/, (m) => `${m[1]}% para ${one(m[2])}, ${m[3]}% para ${one(m[4])} y ${m[5]}% para ${one(m[6])}`],
    [/^(.+) \((\d+)%\), (.+) \((\d+)%\) and (.+) \((\d+)%\)$/, (m) => `${one(m[1])} (${m[2]}%), ${one(m[3])} (${m[4]}%) y ${one(m[5])} (${m[6]}%)`],
    [/^Paid (\$[\d,.]+)( in cash)?\. Thank you!(?: That includes your (\$[\d,.]+) donation(?:: (.+))?\. Thank you!)?$/,
      (m) => `Pagado: ${m[1]}${m[2] ? " en efectivo" : ""}. ¡Gracias!` + (m[3] ? ` Incluye tu donación de ${m[3]}${m[4] ? `: ${charityList(m[4])}` : ""}. ¡Gracias!` : "")],
    [/^Paid (\$[\d,.]+)$/, (m) => `Pagado: ${m[1]}`],
    [/^, including a (\$[\d,.]+) donation\. Thank you!$/, (m) => `, incluida una donación de ${m[1]}. ¡Gracias!`],
    [/^Price: (\$[\d,.]+)$/, (m) => `Precio: ${m[1]}`],
    [/^Access code (.+)$/, (m) => `Código de acceso ${m[1]}`],
    [/^((?:Mowing|Bin Cleaning|Gutters)(?: \+ [^]+?)?) on (.+?) at (.+)$/, (m) => `${services(m[1])} el ${m[2]} en ${m[3]}`],
    [/^(Mowing(?: \+ .+)+)$/, (m) => services(m[1])],
    [/^Arriving between (.+) and (.+)\.$/, (m) => `Llegada entre ${m[1]} y ${m[2]}.`],
    [/^Finished at (.+)\. Thank you!$/, (m) => `Terminamos a las ${m[1]}. ¡Gracias!`],
    [/^Available for (.+) visits$/, (m) => `Disponible para visitas del ${esDate(m[1]).replace(" – ", " al ")}`],
    [/^No charge\. Seasonal: (.+)$/, (m) => `Sin costo. De temporada: ${esDate(m[1]).replace(" – ", " al ")}`],
    [/^(.+) \| (.+)$/, (m) => (ES[m[1]] ? `${ES[m[1]]} | ${m[2]}` : null)],
  ];

  function translate(text) {
    if (lang !== "es" || !text) return text;
    const key = text.replace(/\s+/g, " ").trim();
    if (!key || !/[A-Za-z]/.test(key)) return text;
    let out = ES[key];
    if (out === undefined) {
      for (const [re, fn] of PATTERNS) {
        const m = key.match(re);
        if (m) { const r = fn(m); if (r != null) { out = r; break; } }
      }
    }
    if (out === undefined || out === key) return text;
    // Keep the spacing around the phrase (inline text like " in cash" depends on it).
    const lead = text.match(/^\s*/)[0], trail = text.match(/\s*$/)[0];
    return lead + out + trail;
  }

  const ATTRS = ["placeholder", "aria-label", "title", "alt"];
  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement && node.parentElement.closest("script,style,[data-no-i18n]")) return;
      const t = translate(node.data);
      if (t !== node.data) node.data = t;
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.matches("script,style,[data-no-i18n]")) return;
      for (const a of ATTRS) {
        const v = node.getAttribute(a);
        if (v) { const t = translate(v); if (t !== v) node.setAttribute(a, t); }
      }
      if (node.tagName === "INPUT" && (node.type === "submit" || node.type === "button") && node.value) node.value = translate(node.value);
      for (const child of node.childNodes) translateNode(child);
    }
  }

  // Dates and times in Spanish (pages format them with the browser's default locale).
  if (lang === "es") {
    const loc = (l) => (l === undefined || l === null || (Array.isArray(l) && !l.length) ? "es-US" : l);
    const d = Date.prototype.toLocaleDateString, tm = Date.prototype.toLocaleTimeString;
    Date.prototype.toLocaleDateString = function (l, o) { return d.call(this, loc(l), o); };
    Date.prototype.toLocaleTimeString = function (l, o) { return tm.call(this, loc(l), o); };
  }

  // A small "Español / English" switch in the header.
  function addSwitch() {
    const row = document.querySelector(".header-row");
    if (!row || row.querySelector(".lang-switch")) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-sm lang-switch";
    b.setAttribute("data-no-i18n", "");
    b.lang = lang === "es" ? "en" : "es";
    b.textContent = lang === "es" ? "English" : "Español";
    b.setAttribute("aria-label", lang === "es" ? "Switch to English" : "Ver en español");
    b.addEventListener("click", () => {
      const next = lang === "es" ? "en" : "es";
      try { localStorage.setItem("lang", next); } catch {}
      const u = new URL(location.href); u.searchParams.set("lang", next); location.replace(u.toString());
    });
    const cta = row.querySelector(".header-cta, .btn");
    row.insertBefore(b, cta || null);
  }

  function start() {
    addSwitch();
    if (lang !== "es") return;
    document.title = translate(document.title);
    translateNode(document.body);
    new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === "characterData") translateNode(r.target);
        else if (r.type === "attributes") translateNode(r.target);
        else r.addedNodes.forEach(translateNode);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }

  window.I18N = { lang, t: translate };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
