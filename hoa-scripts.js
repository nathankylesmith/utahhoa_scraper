// JavaScript Document

//Bind with Delay
(function($) {
    $.fn.bindWithDelay = function(type, data, fn, timeout, throttle) {
        var wait = null;
        var lastExec = 0;
        if ($.isFunction(data)) {
            throttle = timeout;
            timeout = fn;
            fn = data;
            data = undefined;
        }
        function handler(event) {
            var context = this;
            var args = arguments;
            var elapsed = +new Date() - lastExec;
            function exec() {
                lastExec = +new Date();
                fn.apply(context, args);
            }
            if (throttle && elapsed > timeout) {
                exec();
            } else {
                clearTimeout(wait);
                wait = setTimeout(exec, timeout);
            }
        }
        return this.on(type, data, handler);
    };
})(jQuery);

// SHOW ENTITY
function showEntity($inPID){
    if (Number.isInteger($inPID) === true) {
        $('#areaResult').html('<p class="text-center"><img src="assets/img/bx_loader.gif" alt=""></p>');
        $.ajax({
            method:"POST",
            url:"assets/js/hoa-ajax.php",
            dataType:'html',
            data:{f:'l',p:$inPID},
            success:function(retVal){ $('#areaResult').html(retVal); },
            error:function(retVal){ $('#areaResult').html(retVal); }
        });
    }
    else {
        alert('an invalid variable was passsed');
    }
}

$(document).ready( ()=>{
	$('#HOAsearch').trigger('focus');
    $('.utds-citizen-experience-wrapper').append('<button id="btnHOAwebsite" type="button" class="btn float-right"><i class="material-icons">keyboard_double_arrow_left</i>Return to HOA Website</button>');
});

// SEARCH
$('#HOAsearch').bindWithDelay("keyup",function(){
    if ($('#HOAsearch').val().length > 0) {
        $('#areaResult').html('<p class="text-center"><img src="assets/img/bx_loader.gif" alt=""> Searching... one moment please.</p>');
        $.ajax({
            method:"POST",
            url:"assets/js/hoa-ajax.php",
            dataType:'html',
            data:{f:'s',v:$('#HOAsearch').val()},
            success:function(retVal){ $('#areaResult').html(retVal); },
            error:function(retVal){ $('#areaResult').html(retVal); }
        });
    }
    else {
        $('#areaResult').html('<div class="alert alert-info text-center">Please enter a name or registration number to search for.</div>')
    }
},200);

// LOAD ENTITY
$(document).on('click','.link-view',function(){
	var pid = $(this).closest('tr').data('pid');
    $('#areaResult').html('<p class="text-center"><img src="assets/img/bx_loader.gif" alt=""> Loading... one moment please.</p>');
    $.ajax({
        method:"POST",
        url:"assets/js/hoa-ajax.php",
        dataType:'html',
        data:{f:'d',v:pid},
        success:function(retVal){ $('#areaResult').html(retVal); },
        error:function(retVal){ $('#areaResult').html(retVal); }
    });
});

// LIST RESULTS
$(document).on('click','#btnList',function(){
    $('#areaResult').html('<p class="text-center"><img src="assets/img/bx_loader.gif" alt=""> Loading... one moment please.</p>');
    $.ajax({
        method:"POST",
        url:"assets/js/hoa-ajax.php",
        dataType:'html',
        data:{f:'l'},
        success:function(retVal){ $('#areaResult').html(retVal); },
        error:function(retVal){ $('#areaResult').html(retVal); }
    });
});

// RETURN TO HOA WEBSITE
$(document).on('click','#btnHOAwebsite',function(){
   window.location.href = "https://commerce.utah.gov/hoa/"; 
});