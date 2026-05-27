/**
 * RULES — Gmail-search query → labels to apply.
 *
 * Ported from `label_queries.json`. Since the label tree is FLATTENED (no
 * nested labels), each former `Parent/Leaf` pair is translated to TWO flat
 * labels (`Parent` and `Leaf`).
 *
 * Label names follow the project convention: lowercase, hyphenated for
 * multi-word, no non-alphanumeric characters other than `-` and `_`.
 * `getOrCreateLabel_` in Code.gs normalizes any drift at runtime, but
 * keeping the source clean avoids surprises in this file.
 *
 * To add a new rule, append an object {query, labels}. Queries use Gmail
 * search syntax — test in the Gmail web UI by pasting into the search bar.
 */

const RULES = [
  // ============ bills ============
  { query: 'from:(telkomsa.net OR telkom.co.za)', labels: ['bills', 'telkom'] },
  { query: 'from:vodacom.co.za', labels: ['bills', 'vodacom'] },
  { query: 'from:kingprice.co.za', labels: ['bills', 'kingprice'] },
  { query: 'from:liberty.co.za', labels: ['bills', 'liberty'] },
  { query: 'from:sars.gov.za', labels: ['bills', 'sars'] },

  // ============ finance ============
  { query: 'from:(fnbstatements.co.za OR fnb.co.za)', labels: ['finance', 'fnb'] },
  { query: 'from:(absa.co.za OR absacapital.com)', labels: ['finance', 'absa'] },
  { query: 'from:stripe.com', labels: ['finance', 'stripe'] },
  { query: 'from:wirexapp.com', labels: ['finance', 'wirex'] },
  { query: 'from:wise.com', labels: ['finance', 'wise'] },
  { query: 'from:discovery.co.za', labels: ['finance', 'discovery'] },
  { query: 'from:(xm.com OR xmglobal.com)', labels: ['finance', 'xm'] },

  // ============ newsletters ============
  { query: 'from:medium.com', labels: ['newsletters', 'medium'] },
  { query: 'from:seekingalpha.com', labels: ['newsletters', 'seekingalpha'] },
  { query: 'from:flippa.com', labels: ['newsletters', 'flippa'] },
  { query: 'from:coursera.org', labels: ['newsletters', 'coursera'] },
  { query: 'from:japanesepod101.com', labels: ['newsletters', 'japanesepod101'] },
  { query: 'from:(mexc.sg OR mexc.com)', labels: ['newsletters', 'mexc'] },
  { query: 'from:okx.com', labels: ['newsletters', 'okx'] },
  { query: 'from:(gate.io OR gate.com)', labels: ['newsletters', 'gate'] },
  { query: 'from:plus500.com', labels: ['newsletters', 'plus500'] },
  { query: 'from:stackshare.io', labels: ['newsletters', 'stackshare'] },
  { query: 'from:tutorialsdojo.com', labels: ['newsletters', 'tutorialsdojo'] },
  { query: 'from:evernote.com', labels: ['newsletters', 'evernote'] },
  { query: 'from:livescribe.com', labels: ['newsletters', 'livescribe'] },
  { query: 'from:quora.com', labels: ['newsletters', 'quora'] },
  { query: 'from:wordpress.com', labels: ['newsletters', 'wordpress'] },
  { query: 'from:meetup.com', labels: ['newsletters', 'meetup'] },
  { query: 'from:offerzen.com', labels: ['newsletters', 'offerzen'] },
  { query: 'from:bitget.com', labels: ['newsletters', 'bitget'] },
  { query: 'from:etoro.com', labels: ['newsletters', 'etoro'] },
  { query: 'from:ideabrowser.com', labels: ['newsletters', 'ideabrowser'] },
  { query: 'from:justinwelsh.me', labels: ['newsletters', 'justinwelsh'] },
  { query: 'from:linuxacademy.com', labels: ['newsletters', 'linuxacademy'] },
  { query: 'from:lumosity.com', labels: ['newsletters', 'lumosity'] },
  { query: 'from:jobleads.com', labels: ['newsletters', 'jobleads'] },
  { query: 'from:maxmahershow.com', labels: ['newsletters', 'maxmahershow'] },
  { query: 'from:openai.com', labels: ['newsletters', 'openai'] },
  { query: 'from:scrimba.com', labels: ['newsletters', 'scrimba'] },
  { query: 'from:wallmine.com', labels: ['newsletters', 'wallmine'] },
  { query: 'from:pnet.co.za', labels: ['newsletters', 'pnet'] },
  { query: 'from:tradingview.com', labels: ['newsletters', 'tradingview'] },
  { query: 'from:xt.com', labels: ['newsletters', 'xt'] },
  { query: 'from:kraken.com', labels: ['newsletters', 'kraken'] },
  { query: 'from:ein-itin.com', labels: ['newsletters', 'ein-itin'] },
  { query: 'from:juliangoldie.com', labels: ['newsletters', 'juliangoldie'] },
  { query: 'from:patreon.com', labels: ['newsletters', 'patreon'] },
  { query: 'from:cal.com', labels: ['newsletters', 'cal'] },
  { query: 'from:discoursemail.com', labels: ['newsletters', 'discourse'] },
  { query: 'from:replit.com', labels: ['newsletters', 'replit'] },

  // ============ notifications ============
  { query: 'from:apple.com', labels: ['notifications', 'apple'] },
  { query: 'from:google.com', labels: ['notifications', 'google'] },
  { query: 'from:bybit.com', labels: ['notifications', 'bybit'] },
  { query: 'from:slack.com', labels: ['notifications', 'slack'] },
  { query: 'from:youtube.com', labels: ['notifications', 'youtube'] },
  { query: 'from:binance.com', labels: ['notifications', 'binance'] },
  { query: 'from:coinex.com', labels: ['notifications', 'coinex'] },
  { query: 'from:mexc.link', labels: ['notifications', 'mexc'] },
  { query: 'from:remote.com', labels: ['notifications', 'remote'] },
  { query: 'from:coinbase.com', labels: ['notifications', 'coinbase'] },
  { query: 'from:cex.io', labels: ['notifications', 'cex'] },
  { query: 'from:docusign.net', labels: ['notifications', 'docusign'] },
  { query: 'from:payoneer.com', labels: ['notifications', 'payoneer'] },
  { query: 'from:luno.com', labels: ['notifications', 'luno'] },

  // ============ personal ============
  { query: 'from:gmail.com', labels: ['personal', 'gmail'] },
  { query: 'from:hotmail.com', labels: ['personal', 'hotmail'] },
  { query: 'from:icloud.com', labels: ['personal', 'icloud'] },
  { query: 'from:yahoo.com', labels: ['personal', 'yahoo'] },

  // ============ receipts ============
  { query: 'from:acloud.guru', labels: ['receipts', 'acloud'] },
  { query: 'from:jetbrains.com', labels: ['receipts', 'jetbrains'] },

  // ============ shopping ============
  { query: 'from:istore.co.za', labels: ['shopping', 'istore'] },

  // ============ social ============
  { query: 'from:linkedin.com', labels: ['social', 'linkedin'] },

  // ============ travel ============
  { query: 'from:booking.com', labels: ['travel', 'booking'] },

  // ============ work ============
  { query: 'from:vpmteam.co.za', labels: ['work', 'vpm'] },
  { query: 'from:busyweb.co.za', labels: ['work', 'busyweb'] },
  { query: 'from:amazon.com', labels: ['work', 'aws'] },
  { query: 'from:github.com', labels: ['work', 'github'] },
  { query: 'from:notion.so', labels: ['work', 'notion'] },
  { query: 'from:pathosethos.com', labels: ['work', 'pathosethos'] },
  { query: 'from:relevant.us', labels: ['work', 'relevant'] },
  { query: 'from:surgenly.com', labels: ['work', 'surgenly'] },
  { query: 'from:trello.com', labels: ['work', 'trello'] },
  { query: 'from:veritybiosciences.com', labels: ['work', 'verity'] },
  { query: 'from:iq.aws', labels: ['work', 'awsiq'] },
  { query: 'from:datachef.co', labels: ['work', 'datachef'] },
  { query: 'from:ioco.tech', labels: ['work', 'ioco'] },
  { query: 'from:simola.co.za', labels: ['work', 'simola'] },
];

const SUBJECT_RULES = [
  {
    query: 'subject:(receipt OR invoice OR "order confirmation" OR "your order" OR "thank you for your order" OR "thank you for your purchase")',
    labels: ['receipts'],
  },
  {
    query: 'subject:("login from" OR "new sign-in" OR "new sign in" OR "your trade" OR "successful trade" OR "purchase for" OR "someone is accessing" OR "unusual sign-in" OR "security alert")',
    labels: ['notifications'],
  },
  {
    // OTP / one-time-code mail. Comes from hundreds of senders so we match by
    // subject patterns. Additive — also picks up notifications via the rule
    // above for the security-alert variants. The otp label flags time-sensitive
    // login codes for quick triage.
    query: 'subject:("verification code" OR OTP OR "one-time password" OR "one time password" OR "your code" OR "login code" OR "security code" OR "authentication code" OR "passcode" OR "two-factor" OR "2fa code" OR "confirmation code" OR "access code" OR "sign-in code" OR "sign in code")',
    labels: ['otp'],
  },
];
