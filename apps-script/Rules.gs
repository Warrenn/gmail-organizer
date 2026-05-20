/**
 * RULES — Gmail-search query → labels to apply.
 *
 * Ported from `label_queries.json`. Since the label tree is FLATTENED (no
 * nested labels), each former `Parent/Leaf` pair is translated to TWO flat
 * labels (`Parent` and `Leaf`).
 *
 * To add a new rule, append an object {query, labels}. Queries use Gmail
 * search syntax — test in the Gmail web UI by pasting into the search bar.
 */

const RULES = [
  // ============ Bills ============
  { query: 'from:(telkomsa.net OR telkom.co.za)', labels: ['Bills', 'Telkom'] },
  { query: 'from:vodacom.co.za', labels: ['Bills', 'Vodacom'] },
  { query: 'from:kingprice.co.za', labels: ['Bills', 'Kingprice'] },
  { query: 'from:liberty.co.za', labels: ['Bills', 'Liberty'] },
  { query: 'from:sars.gov.za', labels: ['Bills', 'SARS'] },

  // ============ Finance ============
  { query: 'from:(fnbstatements.co.za OR fnb.co.za)', labels: ['Finance', 'FNB'] },
  { query: 'from:(absa.co.za OR absacapital.com)', labels: ['Finance', 'ABSA'] },
  { query: 'from:stripe.com', labels: ['Finance', 'Stripe'] },
  { query: 'from:wirexapp.com', labels: ['Finance', 'Wirex'] },
  { query: 'from:wise.com', labels: ['Finance', 'Wise'] },
  { query: 'from:discovery.co.za', labels: ['Finance', 'Discovery'] },
  { query: 'from:(xm.com OR xmglobal.com)', labels: ['Finance', 'XM'] },

  // ============ Newsletters ============
  { query: 'from:medium.com', labels: ['Newsletters', 'medium'] },
  { query: 'from:seekingalpha.com', labels: ['Newsletters', 'Seekingalpha'] },
  { query: 'from:flippa.com', labels: ['Newsletters', 'Flippa'] },
  { query: 'from:coursera.org', labels: ['Newsletters', 'Coursera'] },
  { query: 'from:japanesepod101.com', labels: ['Newsletters', 'Japanesepod101'] },
  { query: 'from:(mexc.sg OR mexc.com)', labels: ['Newsletters', 'Mexc'] },
  { query: 'from:okx.com', labels: ['Newsletters', 'Okx'] },
  { query: 'from:(gate.io OR gate.com)', labels: ['Newsletters', 'Gate'] },
  { query: 'from:plus500.com', labels: ['Newsletters', 'Plus500'] },
  { query: 'from:stackshare.io', labels: ['Newsletters', 'Stackshare'] },
  { query: 'from:tutorialsdojo.com', labels: ['Newsletters', 'Tutorialsdojo'] },
  { query: 'from:evernote.com', labels: ['Newsletters', 'Evernote'] },
  { query: 'from:livescribe.com', labels: ['Newsletters', 'Livescribe'] },
  { query: 'from:quora.com', labels: ['Newsletters', 'Quora'] },
  { query: 'from:wordpress.com', labels: ['Newsletters', 'Wordpress'] },
  { query: 'from:meetup.com', labels: ['Newsletters', 'Meetup'] },
  { query: 'from:offerzen.com', labels: ['Newsletters', 'Offerzen'] },
  { query: 'from:bitget.com', labels: ['Newsletters', 'Bitget'] },
  { query: 'from:etoro.com', labels: ['Newsletters', 'Etoro'] },
  { query: 'from:ideabrowser.com', labels: ['Newsletters', 'ideabrowser'] },
  { query: 'from:justinwelsh.me', labels: ['Newsletters', 'Justinwelsh'] },
  { query: 'from:linuxacademy.com', labels: ['Newsletters', 'Linuxacademy'] },
  { query: 'from:lumosity.com', labels: ['Newsletters', 'Lumosity'] },
  { query: 'from:jobleads.com', labels: ['Newsletters', 'Jobleads'] },
  { query: 'from:maxmahershow.com', labels: ['Newsletters', 'Maxmahershow'] },
  { query: 'from:openai.com', labels: ['Newsletters', 'Openai'] },
  { query: 'from:scrimba.com', labels: ['Newsletters', 'Scrimba'] },
  { query: 'from:wallmine.com', labels: ['Newsletters', 'Wallmine'] },
  { query: 'from:pnet.co.za', labels: ['Newsletters', 'Pnet'] },
  { query: 'from:tradingview.com', labels: ['Newsletters', 'Tradingview'] },
  { query: 'from:xt.com', labels: ['Newsletters', 'Xt'] },
  { query: 'from:kraken.com', labels: ['Newsletters', 'Kraken'] },
  { query: 'from:ein-itin.com', labels: ['Newsletters', 'Ein-Itin'] },
  { query: 'from:juliangoldie.com', labels: ['Newsletters', 'Juliangoldie'] },
  { query: 'from:patreon.com', labels: ['Newsletters', 'Patreon'] },
  { query: 'from:cal.com', labels: ['Newsletters', 'Cal'] },
  { query: 'from:discoursemail.com', labels: ['Newsletters', 'Discourse'] },
  { query: 'from:replit.com', labels: ['Newsletters', 'Replit'] },

  // ============ Notifications ============
  { query: 'from:apple.com', labels: ['Notifications', 'Apple'] },
  { query: 'from:google.com', labels: ['Notifications', 'Google'] },
  { query: 'from:bybit.com', labels: ['Notifications', 'Bybit'] },
  { query: 'from:slack.com', labels: ['Notifications', 'Slack'] },
  { query: 'from:youtube.com', labels: ['Notifications', 'Youtube'] },
  { query: 'from:binance.com', labels: ['Notifications', 'Binance'] },
  { query: 'from:coinex.com', labels: ['Notifications', 'Coinex'] },
  { query: 'from:mexc.link', labels: ['Notifications', 'Mexc'] },
  { query: 'from:remote.com', labels: ['Notifications', 'Remote'] },
  { query: 'from:coinbase.com', labels: ['Notifications', 'Coinbase'] },
  { query: 'from:cex.io', labels: ['Notifications', 'Cex'] },
  { query: 'from:docusign.net', labels: ['Notifications', 'Docusign'] },
  { query: 'from:payoneer.com', labels: ['Notifications', 'Payoneer'] },
  { query: 'from:luno.com', labels: ['Notifications', 'Luno'] },

  // ============ Personal ============
  { query: 'from:gmail.com', labels: ['Personal', 'Gmail'] },
  { query: 'from:hotmail.com', labels: ['Personal', 'Hotmail'] },
  { query: 'from:icloud.com', labels: ['Personal', 'iCloud'] },
  { query: 'from:yahoo.com', labels: ['Personal', 'Yahoo'] },

  // ============ Receipts ============
  { query: 'from:acloud.guru', labels: ['Receipts', 'Acloud'] },
  { query: 'from:jetbrains.com', labels: ['Receipts', 'Jetbrains'] },

  // ============ Shopping ============
  { query: 'from:istore.co.za', labels: ['Shopping', 'iStore'] },

  // ============ Social ============
  { query: 'from:linkedin.com', labels: ['Social', 'LinkedIn'] },

  // ============ Travel ============
  { query: 'from:booking.com', labels: ['Travel', 'Booking'] },

  // ============ Work ============
  { query: 'from:vpmteam.co.za', labels: ['Work', 'VPM'] },
  { query: 'from:busyweb.co.za', labels: ['Work', 'Busyweb'] },
  { query: 'from:amazon.com', labels: ['Work', 'AWS'] },
  { query: 'from:github.com', labels: ['Work', 'Github'] },
  { query: 'from:notion.so', labels: ['Work', 'Notion'] },
  { query: 'from:pathosethos.com', labels: ['Work', 'PathosEthos'] },
  { query: 'from:relevant.us', labels: ['Work', 'Relevant'] },
  { query: 'from:surgenly.com', labels: ['Work', 'Surgenly'] },
  { query: 'from:trello.com', labels: ['Work', 'Trello'] },
  { query: 'from:veritybiosciences.com', labels: ['Work', 'Verity'] },
  { query: 'from:iq.aws', labels: ['Work', 'AWSIQ'] },
  { query: 'from:datachef.co', labels: ['Work', 'Datachef'] },
  { query: 'from:ioco.tech', labels: ['Work', 'IOCO'] },
  { query: 'from:simola.co.za', labels: ['Work', 'Simola'] },
];

const SUBJECT_RULES = [
  {
    query: 'subject:(receipt OR invoice OR "order confirmation" OR "your order" OR "thank you for your order" OR "thank you for your purchase")',
    labels: ['Receipts'],
  },
  {
    query: 'subject:("login from" OR "new sign-in" OR "new sign in" OR "your trade" OR "successful trade" OR "purchase for" OR "someone is accessing" OR "unusual sign-in" OR "security alert")',
    labels: ['Notifications'],
  },
  {
    // OTP / one-time-code mail. Comes from hundreds of senders so we match by
    // subject patterns. Additive — also picks up Notifications via the rule
    // above for the security-alert variants. The OTP label flags time-sensitive
    // login codes for quick triage.
    query: 'subject:("verification code" OR OTP OR "one-time password" OR "one time password" OR "your code" OR "login code" OR "security code" OR "authentication code" OR "passcode" OR "two-factor" OR "2fa code" OR "confirmation code" OR "access code" OR "sign-in code" OR "sign in code")',
    labels: ['OTP'],
  },
];
