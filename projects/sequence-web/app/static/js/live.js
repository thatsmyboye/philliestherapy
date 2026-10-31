/* Sequence Baseball — SSE live update client */

(function () {
  'use strict';

  /**
   * Open an SSE connection to `url` and call `handler(data)` for each event.
   * Automatically reconnects on error with exponential backoff (max 30s).
   */
  function openSSE(url, handler) {
    let retryMs = 2000;
    let es;

    function connect() {
      es = new EventSource(url);

      es.onmessage = function (e) {
        try {
          handler(JSON.parse(e.data));
        } catch (_) {}
        retryMs = 2000; // reset backoff on successful message
      };

      es.onerror = function () {
        es.close();
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 30000);
      };
    }

    connect();
    return { close: function () { es && es.close(); } };
  }

  /* ── Today's games ticker ── */
  var gamesContainer = document.getElementById('live-games');
  if (gamesContainer) {
    var gameState = {};

    openSSE('/games/stream', function (data) {
      var gk = data.game_pk;
      if (!gk) return;
      gameState[gk] = data;
      renderGames();
    });

    function renderGames() {
      var html = Object.values(gameState).map(function (g) {
        var score = (g.status === 'In Progress' || g.away_score != null)
          ? (g.away_score + '-' + g.home_score)
          : '';
        var inning = g.inning ? (g.inning_half + ' ' + g.inning) : g.status;
        return '<div class="game-chip">'
          + '<span class="teams">' + g.away + ' @ ' + g.home + '</span>'
          + (score ? '<span class="score">' + score + '</span>' : '')
          + '<br><span class="status">' + inning + '</span>'
          + '</div>';
      }).join('');
      gamesContainer.innerHTML = html || '<span class="muted">No games in progress</span>';
    }
  }

  /* ── Live steal alert feed ── */
  var stealFeed = document.getElementById('live-steal-feed');
  if (stealFeed) {
    openSSE('/steal/stream', function (data) {
      var row = document.createElement('tr');
      var stars = starsHtml(data.difficulty || 0);
      var result = data.success ? '<span class="delta-pos">SB</span>' : '<span class="delta-neg">CS</span>';
      row.innerHTML =
        '<td>' + result + '</td>'
        + '<td>' + (data.runner || '') + '</td>'
        + '<td>' + stars + '</td>'
        + '<td class="muted">' + (data.pitcher || '') + ' / ' + (data.catcher || '') + '</td>'
        + '<td class="muted">' + (data.inning || '') + '</td>';
      stealFeed.insertBefore(row, stealFeed.firstChild);
      while (stealFeed.children.length > 30) {
        stealFeed.removeChild(stealFeed.lastChild);
      }
    });
  }

  function starsHtml(n) {
    var full = Math.floor(n);
    var html = '';
    for (var i = 0; i < 5; i++) {
      html += i < full ? '★' : '☆';
    }
    return '<span style="color:var(--yellow);letter-spacing:-1px">' + html + '</span>';
  }
})();
