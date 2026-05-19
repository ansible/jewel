/*************************************************
 * Copyright (c) 2016 Ansible, Inc.
 *
 * All Rights Reserved
 *************************************************/

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
}

$(function() {

  // Add syntax highlighting to examples in description.
  $('.description pre').addClass('prettyprint');
  prettyPrint();

  // Make links from relative URLs to resources.
  $('span.str').each(function() {
    const s = $(this).text();
    const m = s.match(/^"(\/[A-Za-z0-9_.~:/?#[\]@!$&'()*+,;=%-]+\/(?:\?[A-Za-z0-9_.~:/?#[\]@!$&'()*+,;=%-]*)?)"$/);
    if (m) {
      const a = document.createElement('a');
      a.href = encodeURI(m[1]);
      a.textContent = m[1];
      $(this).empty().append('"').append(a).append('"');
    }
  });

  // Make links for all inventory script hosts.
  $('.request-info .pln').filter(function() {
    return $(this).text() === 'script';
  }).each(function() {
    $('.response-info span.str').filter(function() {
      return $(this).text() === '"hosts"';
    }).each(function() {
      $(this).nextUntil('span.pun:contains("]")').filter('span.str').each(function() {
        if ($(this).text().match(/^".+"$/)) {
          const s = $(this).text().replaceAll('"', '');
          const a = document.createElement('a');
          a.href = `?host=${encodeURIComponent(s)}`;
          a.textContent = s;
          $(this).empty().append('"').append(a).append('"');
        }
        else if ($(this).text() !== '"') {
          const s = $(this).text();
          const a = document.createElement('a');
          a.href = `?host=${encodeURIComponent(s)}`;
          a.textContent = s;
          $(this).empty().append(a);
        }
      });
    });
  });

  // Add classes/icons for dynamically showing/hiding help.
  if ($('.description').html()) {
    $('.description').addClass('prettyprint').parent().css('float', 'none');
    $('.hidden a.hide-description').prependTo('.description');
    $('a.hide-description').on('click', function() {
      $(this).tooltip('hide');
      $('.description').slideUp('fast');
      return false;
    });
    $('.hidden a.toggle-description').appendTo('.page-header h1');
    $('a.toggle-description').on('click', function() {
      $(this).tooltip('hide');
      $('.description').slideToggle('fast');
      return false;
    });
  }

  $('[data-toggle="tooltip"]').tooltip();

  if ($(globalThis).scrollTop() >= 115) {
    $('body').addClass('show-title');
  }
  $(globalThis).on('scroll', function() {
    if ($(globalThis).scrollTop() >= 115) {
      $('body').addClass('show-title');
    }
    else {
      $('body').removeClass('show-title');
    }
  });

  $('a.resize').on('click', function() {
    $(this).tooltip('hide');
    if ($(this).find('span.glyphicon-resize-full').size()) {
      $(this).find('span.glyphicon').addClass('glyphicon-resize-small').removeClass('glyphicon-resize-full');
      $('.container').addClass('container-fluid').removeClass('container');
      document.cookie = 'api_width=wide; path=/api/';
    }
    else {
      $(this).find('span.glyphicon').addClass('glyphicon-resize-full').removeClass('glyphicon-resize-small');
      $('.container-fluid').addClass('container').removeClass('container-fluid');
      document.cookie = 'api_width=fixed; path=/api/';
    }
    return false;
  });

  if (getCookie('api_width') === 'wide') {
    $('a.resize').trigger('click');
  }

});
